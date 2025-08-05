import os
import pandas as pd
import app

flask_app = app.create_app()
file_path = os.path.join(os.getcwd(), "tmp","VendorsToday_FakeTransactionsx1.csv")

with flask_app.app_context():
    try:
        data = (
            pd.read_excel(file_path) if file_path.endswith('.xlsx')
            else pd.read_csv(file_path, encoding='utf-8')
        )
        
        data.columns = data.columns.str.lower()
        
        if 'vendor' not in data.columns or 'transaction' not in data.columns:
            raise Exception("Missing required field")

        # preprocessing
        data["vendor"] = data["vendor"].fillna("").str.strip()
        data["transaction"] = data["transaction"].fillna("").str.strip()
        data = data.loc[(data["vendor"] != "") & (data["transaction"] != "")]
        data = data.drop_duplicates()
            
        existing = {(v.vendor, v.transaction_descr) for v in app.db.session.query(app.models.Vendor).all()}
        new_entries = [
            app.models.Vendor(vendor=row['vendor'], transaction_descr=row['transaction'], template_id=1)
            for _, row in data.iterrows()
            if (row['vendor'], row['transaction']) not in existing
        ]
        
        app.db.session.add_all(new_entries)
        app.db.session.commit()
    except Exception as e:
        app.db.session.rollback()
        raise