import os
import numpy as np
import pandas as pd
from pandas import DataFrame
from io import BytesIO
from datetime import date
from celery import shared_task
from . import helpers, db, models, s3_client

@shared_task()
def createTable(model_name, object_name):
    """Creates and formats itemized table from given Excel or CSV file
    and gets chart of account predictions
    """ 
    try:
        filepath = os.path.join("/tmp", object_name)
        s3_client.download_file(os.environ.get("BUCKET_NAME"), object_name, filepath)

        data = (
            pd.read_excel(filepath) if filepath.endswith('.xlsx')
            else pd.read_csv(filepath, encoding='utf-8')
        )

        data.columns = data.columns.str.lower()

        if 'memo' in data.columns:
            data.rename(columns={'memo': 'description'}, inplace=True)
            
        if 'description' not in data.columns or 'amount' not in data.columns:
            raise Exception("Missing 'description' or 'amount' column(s)")

        if 'date' not in data.columns:
            data['date'] = ''
            
        dates = pd.to_datetime(data['date'], format='%Y-%m-%d', errors='coerce')
        data['date'] = (
            dates.fillna(pd.Timestamp.today().normalize())
                .dt.strftime('%m-%d-%Y')
        )
        
        data['number'] = ""
        data['payee'] = ""
        data['account'] = ""
       
        unspecified_columns = [col for col in set(data.columns) if col not in {'date', 'number', 'payee', 'account', 'amount', 'description'}]
        data = data[['date', 'number', 'payee', 'account', 'amount', 'description']  + unspecified_columns]
        data[unspecified_columns] = data[unspecified_columns].astype(str)

        # predict chart of accounts
        table = helpers.classify(data, model_name)
        table['initial_account_prediction'] = table['account']
        
        # Step 1: Compute group-level totals and counts in one go
        grouped = table.groupby(['description', 'account'])['amount'].agg(
            total='sum',
            instances='count'
        ).reset_index()

        # Step 2: Merge both metrics into table at once
        table = table.merge(grouped, on=['description', 'account'], how='left')
  
        # unrecognized vednors column(s)
        helpers.group(table)

        table["id"] = range(0, len(table))

        return helpers.serializeDataFrame(table)
    except Exception as e:
        print(e)
        raise
    finally:
        helpers.deleteTmpFile(filepath)
        response = s3_client.delete_object(Bucket=os.environ.get('BUCKET_NAME'), Key=object_name)

@shared_task()
def createExcelFile(serialized_df, template_id):
    df_itemized = helpers.deserializeDataFrame(serialized_df)
    df_itemized = df_itemized.drop(['prediction_confidence', 'group', 'description'], axis=1)
    df_itemized = df_itemized.rename(columns={'old_description': 'description'})

    # save corrections users made (for retraining)
    mask = df_itemized['account'] != df_itemized['initial_account_prediction']
    corrections = df_itemized.loc[mask, ['description', 'account', 'amount']]

    try:
        new_transactions = [models.Transaction(description=row['description'], account=row["account"], amount=row['amount'], template_id=template_id) for _, row in corrections.iterrows()]
        db.session.add_all(new_transactions)
    except Exception as e:
        print(e)
        db.session.rollback()

    db.session.commit()

    csv_file = BytesIO()
    df_itemized.to_csv(csv_file,index=False)
    csv_file.seek(0)

    return csv_file.getvalue()

@shared_task()
def add_chart_of_accounts(object_name, group_name, userID):
    try:
        file_path = os.path.join("/tmp", object_name)
        s3_client.download_file(os.environ.get("BUCKET_NAME"), object_name, file_path)

        data = (
            pd.read_excel(file_path) if file_path.endswith('.xlsx')
            else pd.read_csv(file_path, encoding='utf-8')
        )
        
        data.columns = data.columns.str.lower()
        
        if 'account' not in data.columns:
            raise Exception("Missing required 'account' field")
            
        # create group id and name pair
        group = models.COAIDtoGroup(group_name=group_name)
        db.session.add(group)
        db.session.flush()

        # add entries to COA table
        data["account"] = data["account"].fillna("").str.strip()
        data = data.loc[data["account"] != ""]
        data.drop_duplicates(inplace=True)
        accounts = [models.COA(group_id=group.group_id, account= row["account"]) for _, row in data.iterrows()]
        db.session.add_all(accounts)
        
        # user_coa_access entry
        user_access = models.UserCOAAccess(user_id=userID,group_id=group.group_id, access_level="creator")
        db.session.add(user_access)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(e)
        raise
    finally:
        helpers.deleteTmpFile(file_path)
        response = s3_client.delete_object(Bucket=os.environ.get('BUCKET_NAME'), Key=object_name)

@shared_task()
def register_model(object_name, template_info):
    try:
        file_path = os.path.join("/tmp", object_name)
        s3_client.download_file(os.environ.get("BUCKET_NAME"), object_name, file_path)
        
        data = (
            pd.read_excel(file_path) if file_path.endswith('.xlsx')
            else pd.read_csv(file_path, encoding='utf-8')
        )
        
        data.columns = data.columns.str.lower()

        if 'memo' in data.columns:
            data.rename(columns={'memo': 'description'}, inplace=True)
            
        required = {'description', 'account', 'amount'}
        missing = required - set(data.columns)
        
        if missing:
            raise Exception(f"Missing required columns: {', '.join(missing)}")
            
        # generate unique model name
        while True:
            model_name = helpers.generate_filename()
            existing_entry = db.session.query(models.Template).filter_by(model_name=model_name).first()
            
            if not existing_entry:
                template_info['model_name'] = model_name
                t = models.Template()
                t.from_dict(template_info)
                db.session.add(t)
                db.session.flush()
                break
            
        # remove rows with empty or nan values in any column
        data = data[['description', 'account', 'amount']]
        data["description"] = pd.Series(data["description"]).fillna("").str.strip()
        data = data.loc[data["description"] != ""]
        pd.to_numeric(data['account'], errors='coerce')
        pd.to_numeric(data['amount'], errors='coerce')
        data = data.dropna(subset=['account', 'amount', 'description'])
        data.drop_duplicates()
        data = data.reset_index(drop=True)
            
        # add transactions to database
        transactions = [models.Transaction(description=row['description'], account=row["account"], amount=row['amount'], template_id=t.id) for _, row in data.iterrows()]
        db.session.add_all(transactions)
        db.session.flush()

        # train model
        helpers.train(data, template_info["model_name"])

        # add user-template relationship to database
        u = models.UserTemplateAccess(template_id=t.id,user_id=t.author,access_level="creator")
        db.session.add(u)
        db.session.commit()

    except Exception as e:
        db.session.rollback()
        raise
    finally:
        helpers.deleteTmpFile(file_path)
        response = s3_client.delete_object(Bucket=os.environ.get('BUCKET_NAME'), Key=object_name)