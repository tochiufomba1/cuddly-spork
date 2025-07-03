import os
import pandas as pd
import numpy as np
import pyarrow.feather as feather
import pyarrow as pa
# import psycopg2
import json
import random
from io import BytesIO

import sqlalchemy as sa
from sqlalchemy import or_, asc, and_, update
import sqlalchemy.orm as so
from sqlalchemy import func
from werkzeug.utils import secure_filename
from celery import chain, group 
from celery.result import AsyncResult, GroupResult
from flask import (
    Flask, flash, request, session, url_for, send_from_directory, render_template, send_file, make_response, abort, Response
)

from app import db, models #, client
from app import helpers, tasks
from app.api.errors import bad_request,error_response
from app.api.auth import token_auth
from app.api import bp


ALLOWED_EXTENSIONS = {'xlsx', 'csv'}
UNIVERSAL_TEMPLATE = 34

def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def handle_file_submit(fileObject):
    if fileObject is None:
        return "Please provide complete form"
    elif fileObject.filename == '':
        return "Please provide valid form values"
    elif fileObject and allowed_file(fileObject.filename):
        try:
            filename = secure_filename(fileObject.filename)  
            filepath = os.path.join(os.getcwd(), "tmp", str(random.randint(0, 5000)) + filename) # generate virtually unique filepath
            fileObject.save(filepath)
            return filepath
        except Exception as e:
            return "Server error"
    else:
        return "Server error"

@bp.route("/", defaults={'path':''})
@bp.route('/<path:path>')
def index(path):
    # ping type function
    return {}, 200

''' Authentication Views '''
@bp.route('/api/users/usernames/<string:username>', methods=['GET'])
def check_username(username):
    if(db.session.scalar(sa.select(models.Users).where(models.Users.username == username))):
        return {"available": False}
    return {"available": True}

@bp.route('/api/users/emails/<string:email>', methods=['GET'])
def check_email(email):
    if(db.session.scalar(sa.select(models.Users).where(models.Users.email == email))):
        return {"valid": False}
    return {"valid": True}

@bp.route('/api/users', methods=['POST'])
def register():
    data = request.get_json()
    # print(f"data: {data}")
    if 'username' not in data or 'email' not in data or 'password' not in data:
        return bad_request('Submission must include username, email and password fields')
    if db.session.scalar(sa.select(models.Users).where(models.Users.username == data['username'])):
        return bad_request('Please provide a different username')
    if db.session.scalar(sa.select(models.Users).where(models.Users.email == data['email'])):
        return bad_request('Please provide a different email address')
    user = models.Users()
    user.from_dict(data, new_user=True)
    db.session.add(user)
    db.session.commit()
    return {user.id}, 201

''' End of Authentication Views '''

''' Transaction Categorization Views '''
@bp.route('/api/users/<int:id>/templates', methods=['GET'])
@token_auth.login_required
def send_options(id):
    # user = db.get_or_404(Users, id)
    result = db.session.execute(sa.select(models.Template.title, models.Template.id).join(models.UserTemplateAccess, models.Template.id == models.UserTemplateAccess.template_id).where(models.UserTemplateAccess.user_id == id))
    templates = [{'id': row.id, 'title': row.title} for row in result]
    return {"templates": templates}

@bp.route('/api/users/transactions', methods=['POST'])
@token_auth.login_required
def upload_file():
    file = request.files.get("file", None)
    result_string = handle_file_submit(file)

    if not os.path.exists(result_string):
        if(result_string == 'Server error'):
            print("HERESVX")
            return error_response(500, result_string)
        return bad_request(result_string)
    
    # Verify that user can use requested template
    templateID = request.form.get('template', -1)
    userID = token_auth.current_user().id
    access = db.session.execute(sa.select(models.UserTemplateAccess.access_level).where(models.UserTemplateAccess.user_id == userID and models.UserTemplateAccess.template_id == templateID))

    if access is None:
        bad_request("User doesn't have access to the requested template")

    filename, _ = os.path.splitext(os.path.basename(result_string))
    session["filename"] = filename
    session['templateID'] = int(templateID)
    # session['access'] = access

    template = db.session.scalar(sa.select(models.Template).where(models.Template.id == templateID))
    workflow = tasks.createTable.apply_async(args=[template.model_name, result_string])
    
    return {'url': url_for('api.createTables_status',task_id=workflow.id)}, 202

@bp.route('/api/users/transactions/<task_id>', methods=['GET'])
@token_auth.login_required
def createTables_status(task_id):
    async_result = AsyncResult(task_id)
    
    if async_result.ready():
        if async_result.successful():
            session['bertDescriptions'] = async_result.result
            return  {'status':'success'}, 200
        else:
            # app.logger.error("Parent task failed")
            return {'status':'failed'}, 500 
    else:
        # app.logger.error("Parent task still running")
        return {'status':'pending'}, 202 

@bp.route('/api/tables')
@token_auth.login_required
def data():
    try:
        templateID = session.get('templateID')
        table = helpers.deserializeDataFrame(session.get('bertDescriptions'))
        unresolved_indices = table[table['description'].isin({'unrecognized credit', 'unrecognized debit'})].index.tolist()
        unresolved_transactions = table.loc[unresolved_indices][["old_description",'group']]
        unresolved_transactions = unresolved_transactions.rename(columns={'old_description': 'description'})
        unresolved_transactions['vendor'] = 'Not Assigned'
        unresolved_transactions = unresolved_transactions[['group', 'description', 'vendor']].drop_duplicates(subset='group', keep='first')

        table_summary = table[['description', 'account', 'total', 'instances','prediction_confidence']].drop_duplicates(keep='first')
        COA = list(db.session.scalars(sa.select(models.COA.account).join(models.Template, models.COA.group_id == models.Template.coa_group_id).where(models.Template.id == templateID))) # session.get("templateID")
        vendors = list(db.session.scalars(sa.select(models.Vendor.vendor).filter(or_(models.Vendor.template_id == UNIVERSAL_TEMPLATE, models.Vendor.template_id == templateID)).distinct().order_by(asc(models.Vendor.vendor))))
        category_totals_df = helpers.get_category_totals(table)

        data = {
            'table': table.to_json(orient='records'),
            'summary': table_summary.to_json(orient='records'),
            'unresolved': unresolved_transactions.to_json(orient='records'),
            'category_totals': category_totals_df.to_json(orient='records'),
            'options': json.dumps(COA),
            'vendors': json.dumps(vendors)
        }
        
        return data, 200
    except TypeError as e:
        print(e)
        return {'message': 'Failure'}, 500
    except KeyError as e:
        print(e)
        data = {'message': 'Failure'}
        return data, 500
   
@bp.route("/api/tables/item/<int:rowNum>", methods=['PUT'])
@token_auth.login_required
def updateTable(rowNum):
    data = request.get_json()
    df_itemized = helpers.deserializeDataFrame(session.get('bertDescriptions', None))
    df_itemized.loc[rowNum, 'account'] = data['account'] 

    # Determine if user changed a transaction that is part of a group
    row_description = df_itemized.loc[rowNum, 'description']
    instances = df_itemized['description'].value_counts()[row_description]

    # If not, change particular entry in summary table
    if instances == 1:
        df_summary = helpers.deserializeDataFrame(session.get('summaryPage', None))
        df_summary.loc[df_summary['description'] == row_description, 'account'] = data['account']
    else:
        session['summaryPage'] = helpers.serializeDataFrame(helpers.createSummaryTable(df_itemized))    
    
    # Serialize and save updated table
    session['bertDescriptions'] = helpers.serializeDataFrame(df_itemized)
    
    return {'message': 'Success'}, 200

@bp.route("/api/tables/summary/<int:rowNum>", methods=['PUT'])
@token_auth.login_required
def updateSummaryTable(rowNum):
    data = request.get_json()
    
    # TODO: Handle items with just one instance + items that differ from rest of group
    # logic proposal: get old summary table and find account associated with provide row
    # change row to new account, for itemized table create mask, then change on condition that
    # account matches the old account that was just replaced
  
    # update and save itemized table
    df_itemized = helpers.deserializeDataFrame(session.get('bertDescriptions', None))
    mask = df_itemized['description'] == data['description']
    df_itemized.loc[mask, 'account'] = data['account']
    session['bertDescriptions'] = helpers.serializeDataFrame(df_itemized)
    
    data = {'message': 'Success'}
    return data, 200

@bp.route("/api/tables/resolve/<int:rowNum>", methods=['PUT'])
@token_auth.login_required
def resolve(rowNum):
    request_data = request.get_json()
    vendor = request_data['vendor'].lower()
    group = int(request_data['group'])

    # TODO: Check if vendor is in vendor list
    try:
        df_itemized = helpers.deserializeDataFrame(session.get('bertDescriptions', None))
        unresolved_indices = df_itemized[df_itemized['Description'].isin({'unknown/unrecognized credit', 'unknown/unrecognized debit'})].index.tolist()
        df_unresolved = df_itemized.iloc[unresolved_indices]
        df_summary = df_itemized[['description', 'account', 'total', 'instances','prediction_confidence']].drop_duplicates(keep='first')
    except Exception as e:
        print(e)
        data = {'message': 'Error'}
        return data, 500

    mask = df_itemized['group'] == group
    df_itemized.loc[mask, 'description'] = df_itemized.loc[mask, 'amount'].apply(lambda x: f"{vendor} {'debit' if x < 0 else 'credit'}")

    # create a mapping of Description -> Account with the most Instances
    description_to_account = (
        df_summary.loc[df_summary['description'].isin(df_itemized.loc[mask, 'description'])]
        .groupby('description', as_index=False)
        .apply(lambda group: group.loc[group['instances'].idxmax()])
        [['description', 'account']]
        .set_index('description')['account']
        .to_dict()
    )

    # Add 'Not Assigned' for missing Descriptions
    missing_descriptions = set(df_itemized.loc[mask, 'description']) - set(description_to_account.keys())
    for description in missing_descriptions:
        description_to_account[description] = 'Not Assigned'

    # Map the Account values back to the df_itemized DataFrame
    df_itemized.loc[mask, 'account'] = df_itemized.loc[mask, 'description'].map(description_to_account)    
    
    # Save updated tables in session
    session['bertDescriptions'] = helpers.serializeDataFrame(df_itemized)

    data = {'message': 'Success'}
    return data, 200

@bp.route('/api/vendors', methods=["GET"])
@token_auth.login_required
def get_vendor():
    try:
        userID = token_auth.current_user().id
        templateID = session.get("templateID")
        vendors = db.session.execute(sa.select(models.Vendor.vendor).where(models.Vendor.template_id == UNIVERSAL_TEMPLATE or models.Vendor.template_id == templateID))

        data = {'vendors': [{'name': row.vendor } for row in vendors]}

        return data, 200
    except KeyError as e:
        print(e)
        return error_response(500)

@bp.route('/api/vendors', methods=["POST"])
@token_auth.login_required
def add_vendor():
    # user_id = token_auth.current_user().id
    try:
        # get form data
        vendor_name = request.form.get("vendor")
        public = request.form.get("public")
        transcription_description = request.form.get('description')
        templateID = session.get('templateID')

        # automatically add vendor if the vendor is specific to template
        if public == 'off':
            new_vendor = Vendor(vendor=vendor_name, transaction_descr=transcription_description, template_id=templateID)
            db.session.add(new_vendor)
            db.session.commit()  
            return

        # if not, have chatgpt verify new vendor
        #TODO: Provide list of vendors to prevent duplication
        response = client.responses.create(
            model="gpt-4.1-mini",
            input=f"""Identify the following vendor name: '{vendor_name}' 
            Respond only in JSON using this form: {{'name': <vendor_name> }}.  
            Write the identified vendor in the most commonly accepted way to write it. 
            If the vendor name cannot be identified with at least 95% confidence, respond with {{ 'name': 'error' }}. 
            Do not include any explanation, extra formatting, or text outside the JSON."""
        )
        
        new_vendor_dict = json.loads(response.output_text)
        new_vendor = new_vendor_dict['name']
        
        if(new_vendor == 'error'):
             return bad_request("Vendor couldn't be identified, please try again.")

        new_vendor_entry = Vendor(vendor=new_vendor, transaction_descr=transcription_description, template_id=UNIVERSAL_TEMPLATE)
        db.session.add(new_vendor)
        db.session.commit()  
    except KeyError as e:
        return bad_request("Ensure that all form fields are filled.")
    except Exception as e:
        print(e)
    
@bp.route('/api/export')
@token_auth.login_required
def export():
    itemizedUnloaded = session.get('bertDescriptions', None)
    task = tasks.createExcelFile.apply_async(args=[itemizedUnloaded])
    
    return {'url': url_for('api.export_file',task_id=task.id)}, 202

@bp.route('/api/export/<task_id>')
@token_auth.login_required
def export_file(task_id):
    task = tasks.createExcelFile.AsyncResult(task_id)

    if task.state == 'SUCCESS': 
        file_name = session.get('filename', None) 
        output = BytesIO(task.result)
        return send_file(output, mimetype='text/csv', as_attachment=True, download_name=f"{file_name}_LABELED.csv")
    else:
        if task.state == 'PENDING':
           return {'status':'pending'}, 202 
        elif task.state == 'FAILED':
            return {'status':'failed'}, 500

''' End of Transaction Categorization Views '''

''' Template Creation Views '''
@bp.route('/api/users/<int:id>/coa', methods=['GET'])
@token_auth.login_required
def get_coas(id):
    if token_auth.current_user().id != id:
        return bad_request("Not authorized to access this resource")

    result = db.session.execute(sa.select(models.COAIDtoGroup.group_id, models.COAIDtoGroup.group_name).join(models.UserCOAAccess, models.COAIDtoGroup.group_id == models.UserCOAAccess.group_id).where(models.UserCOAAccess.user_id == id))
    coa_groups = [{'group_id': row.group_id, 'group_name': row.group_name} for row in result]
    return {'coa_groups': coa_groups}

@bp.route('/api/users/coa', methods=['POST'])
@token_auth.login_required
def add_coa():
    userID = token_auth.current_user().id
    coa_name = request.form.get("name", None)
    chart_of_accounts = request.files.get("coa", None)

    result = handle_file_submit(chart_of_accounts)
    if not os.path.exists(result):
        if(result == 'Server error'):
            return error_response(500, result)
        return bad_request(result)
        
    # task that reads the file, puts in coa table + coa access table
    task = tasks.add_chart_of_accounts.apply_async(args=[file_path, group_name, userID]) #replace group_name with info
    return {'job_id': task.id}, 202

@bp.route('/api/users/coa/<task_id>')
@token_auth.login_required
def coa_task_check(task_id):
    task = tasks.add_chart_of_accounts.AsyncResult(task_id)

    if task.state == 'SUCCESS': 
        return {}, 200
    elif task.state == 'FAILED':
        return bad_request("Something")
    else:
        return {}, 202        

@bp.route('/api/users/templates', methods=['POST'])
@token_auth.login_required
def create_model():
    # create dictionary containing information about template
    template_dictionary = {}

    for field in ['title', 'coa_group_id']:
        form_value = request.form.get(field, None)
        if form_value is not None:
            template_dictionary[field] = form_value
        else:
            return bad_request("Please provide completed form")

    template_dictionary['author'] = token_auth.current_user().id
    template_dictionary['published'] = False
    template_dictionary['active'] = True
    
    # check if transaction history file is accessible
    transaction_history = request.files.get("file", None)
    result = handle_file_submit(transaction_history)
    if not os.path.exists(result):
        if(result == 'Server error'):
            return error_response(500, result)

        return bad_request(result) # result will be an error message if saving the file fails

    # start asynchronous task
    workflow = tasks.register_model.apply_async(args=[result, template_dictionary])
    return {"result_id": workflow.id}, 202    

@bp.route('/api/users/templates/<string:task_id>')
@token_auth.login_required
def check_template_progress(task_id):
    # Generic structure TODO: Replace #
    task = tasks.register_model.AsyncResult(task_id)
    # print(task.status)
    # app.logger.error("Task status", task.status)
    if task.state == 'SUCCESS': 
        return {}, 200
    elif task.state == 'FAILURE':
        return {}, 500
    else:
        return {}, 202

@bp.route('/api/users/templates/<int:template_id>', methods=['DELETE'])
@token_auth.login_required
def deactivate_template(template_id):
    user_id = token_auth.current_user().id
    # check if the template exists + user has authorization to deactivate
    authorized = db.session.execute(sa.select(
        models.UserTemplateAccess.template_id, models.UserTemplateAccess.access_level).where(
            and_(models.UserTemplateAccess.user_id == user_id, models.UserTemplateAccess.template_id == template_id)
        )
    )

    if authorized is None:
        return error_response(403, "Unauthorized to delete requested templated")

    db.session.query(Template).filter(Template.id == template_id).update({'active': False})
    db.session.commit()

    return {}, 200

''' End of Template Creation Views '''

''' Marketplace Methods '''
@bp.route('/api/marketplace/templates', methods=['GET'])
@token_auth.login_required
def get_templates():
    # logic
    # consider optional search parameters (these should be paginated)
    return {}, 200

@bp.route('/api/marketplace/templates/<string:tag>', methods=['GET'])
@token_auth.login_required
def get_tag_templates():
    # logic
    # consider optional search parameters (these should be paginated)
    return {}, 200

@bp.route('/api/marketplace/templates', methods=['POST'])
@token_auth.login_required
def publish_template():
    # publish template logic
    return {}, 200

''' End of Marketplace Views '''

''' Resource Views '''
# @app.route('/api/users/<int:userID>/coa', methods=['POST'])
# def get_coa_options(userID):
#     return
