import os
import re
import io
import json
import secrets
import pandas as pd
import numpy as np
import pyarrow as pa
import networkx as nx
import sqlalchemy as sa
import sqlalchemy.orm as so
import pyarrow.feather as feather
from joblib import dump, load
from datasketch import MinHash, MinHashLSH

from sklearn.pipeline import Pipeline
from sklearn.feature_extraction.text import CountVectorizer
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.ensemble import RandomForestClassifier


from app import db, models
from sqlalchemy import func
import fasttext

def write_dict_to_file(data, filename):
    """Writes a dictionary to a file in JSON format.

    Args:
        data (dict): The dictionary to be written.
        filename (str): The name of the file to write to.
    """
    try:
        with open(filename, 'w') as file:
            json.dump(data, file, indent=4) # Use indent for pretty formatting
        print(f"Dictionary successfully written to {filename}")
    except Exception as e:
        print(f"An error occurred: {e}")

def generate_filename():
    return secrets.token_hex(16)

def get_minhash(text):
    m = MinHash(num_perm=128)
    
    for shingle in set(text.split()[:3]): #get_ngrams(text, 3)
        m.update(shingle.encode('utf8'))
        
    return m

def group(table):
    """Groups similar unregonized transactions using MinHash LSH algorithm """
    
    lsh = MinHashLSH(threshold=0.8, num_perm=128)
    minhashes = {}

    unresolved_vendor_indices = table[table['description'].isin({'unrecognized credit', 'unrecognized debit'})].index.tolist()
    
    unresolved_table = table.loc[unresolved_vendor_indices]

    cleaned_vendor_descriptions = unresolved_table['old_description'].str.lower().str.replace(
        r'https?:\/\/\S+|\b(?:re|e)?pay(?:ment|mt|mnt)?s?\b|\b(?:post)?paid|\b(?:pmt|pymnt|pmnt)s?\b|'
        r'(?:merchant\s+)?(?:web)?payment\b|(?:mobile)? \bpurchase(?:s)?\b(?:\s+(?:authorized|at|-visa))?|\bdirect\b|\bdebit\b|'
        r'\b(?:tel(?:ephone)?|(?:initiated)|(?:pending)|ach(?:billpay)?|ccd|ppd|atm|rtp|rbt|visa|misc|nnt|tst|(?:i)?nst|'
        r'return|easysavings|(?:at|&)\b(?!\s*&?\s*t\b))\b|(?:^\s+|\s+$|\s{2,}|\.com\b.*|[^\w\s])|(?:from|www|(?:a|u)mp|httpswww.*)|'
        r'\bdeduction(?:s)?\b|\b(?:web|electronic|checkcard|trans type|name|e2e|online|self|authorized|phone|transaction(?:s)|'
        r'recur(?:ring)?|service(?:s)?|corporate|util|bill(?:pay)?|util_bil(?:l)?|card|ret|sq(?:u)?|on|the|and|of|to)\b|\b(?:al|ak|az|ar|'
        r'ca|co|ct|de|fl|ga|hi|id|il|in(?:s)?|ia|ks|ky|la|me|md|ma|mn|ms|mo|mt|ne|nv|nh|nj|nm|ny|nc|nd|oh|ok|or|pa|ri|'
        r'sc|sd|tn|tx|ut|vt|va|wa|wv|wi|wy|p(o|c)s|edi|pw)\d*\b|\d+(?!co)\w*|[x]{2,}\d*[x]*', 
        ' ', 
        regex=True
    )

    for idx, text in cleaned_vendor_descriptions.items():
        m = get_minhash(text)

        lsh.insert(str(idx), m)

        minhashes[str(idx)] = m
        
    # get graph edges
    all_edges = []
    for key in minhashes.keys():
        edges = [(key, x) for x in lsh.query(minhashes[key])]
        all_edges += edges

    # create graph and find connected components from edges
    G = nx.Graph()
    G.add_edges_from(all_edges)
    connected_components = list(nx.connected_components(G))
    
    # add table column for accessing connection group of each unresolved vendor
    table['group'] = -1
    for index, group in enumerate(connected_components):
        table.loc[[int(item) for item in list(group)], 'group'] = index

    # x_dict = {table.loc[int(next(iter(group))), 'old_description']: list(group) for group in connected_components}
    # with open("output.json", "w") as json_file:
    #     json.dump(x_dict, json_file, indent=4)

    return

def get_fasttext_labels(model_path, series, threshold):
    """Classifies vendor of transasctions using fasttext model"""

    model = fasttext.load_model(model_path)

    series = series.fillna('').astype(str)
    series = series.str.lower().replace(r'\.', '', regex=True).replace(
        r'https?:\/\/\S+|\b(?:re|e)?pay(?:ment|mt|mnt)?s?\b|\b(?:post)?paid|\b(?:pmt|pymnt|pmnt)s?\b|'
        r'(?:merchant\s+)?(?:web)?payment\b|(?:mobile)? \bpurchase(?:s)?\b(?:\s+(?:authorized|at|-visa))?|\bdirect\b|\bdebit\b|'
        r'\b(?:tel(?:ephone)?|(?:initiated)|(?:pending)|ach(?:billpay)?|ccd|ppd|atm|rtp|rbt|visa|misc|nnt|tst|(?:i)?nst|'
        r'return|easysavings|(?:at|&)\b(?!\s*&?\s*t\b))\b|(?:^\s+|\s+$|\s{2,}|\.com\b.*|[^\w\s])|(?:from|www|(?:a|u)mp|httpswww.*)|'
        r'\bdeduction(?:s)?\b|\b(?:web|electronic|checkcard|trans type|name|e2e|online|self|authorized|phone|transaction(?:s)|'
        r'recur(?:ring)?|service(?:s)?|corporate|util|bill(?:pay)?|util_bil(?:l)?|card|ret|sq(?:u)?|on|the|and|of|to)\b|\b(?:al|ak|az|ar|'
        r'ca|co|ct|de|fl|ga|hi|id|il|in(?:s)?|ia|ks|ky|la|me|md|ma|mn|ms|mo|mt|ne|nv|nh|nj|nm|ny|nc|nd|oh|ok|or|pa|ri|'
        r'sc|sd|tn|tx|ut|vt|va|wa|wv|wi|wy|p(o|c)s|edi|pw)\d*\b|\d+(?!co)\w*|[x]{2,}\d*[x]*',
        ' ',
        regex=True
    )

    labels, confidences = model.predict(list(series), k=1)
    
    # remove fasttext formatting from vendor classifications
    cleaned_labels = [
        lbl[0].replace('__label__', '') if prob[0] >= threshold else 'unrecognized' 
        for lbl, prob in zip(labels, confidences)
    ]

    new_series = pd.Series(cleaned_labels, index=series.index)
    
    return new_series

def classify(data, model_name):
    """Predicts the vendors and chart of accounts of given transaction(s)"""

    data.columns = data.columns.str.lower()
    transactions_simplified = get_fasttext_labels(os.path.join(os.getcwd(), "data", "filex6.bin"), data["description"].str.strip(), 0.80)  #predictVendors(transactions, os.path.join(os.getcwd(), "data", "vendors.joblib"), os.path.join(os.getcwd(), "data","ID_CategoryMap.joblib"))
    
    # attach transaction type label (debit or credit, expense or revenue) to each vendor prediction
    vendors_transactionType = transactions_simplified + ' ' + np.where(data['amount'] > 0, 'credit', 'debit')
    
    # classify chart of account for each transaction
    file_path = os.path.join(os.getcwd(), "data", "tes71.joblib") # f"{model_name}.joblib"
    loaded_pipeline = load(file_path)
    categories = loaded_pipeline.predict(vendors_transactionType)
    class_probabilities = loaded_pipeline.predict_proba(vendors_transactionType)

    # get the selected class probability value for each transaction
    highest_probabilities = np.max(class_probabilities, axis=1)
  
    # define thresholds using numpy's select method
    conditions = [
        highest_probabilities < 0.4,
        (highest_probabilities >= 0.4) & (highest_probabilities < 0.7),
        highest_probabilities >= 0.7
    ]
    
    choices = ["Low", "Medium", "High"]
    confidenceGroups = np.select(conditions, choices, "None")

    # update data
    data['account'] = categories
    data['prediction_confidence'] = confidenceGroups
    data = data.rename(columns={'description': 'old_description'})
    data['description'] = vendors_transactionType
    
    return data

def get_category_totals(data):
    """Produces view of chart of accounts and their total expenditures"""
    
    data['amount'].fillna(0)
    
    group = data.groupby(['account'])['amount'].agg(
        total='sum',
    ).reset_index()

    view = data.merge(group, on=['account'], how='left')
    view = view.rename(columns={'total_y':'total'})
    view = data.drop_duplicates(subset=['account'], keep='first')

    view = view[['account','total']]
    
    return view

def deserializeDataFrame(buffer):
    buffReader = pa.BufferReader(buffer)
    df = feather.read_feather(buffReader)
    return df

def serializeDataFrame(df):
    newBuffer = io.BytesIO()
    feather.write_feather(df, newBuffer)
    newBuffer.seek(0)
    return newBuffer.getvalue() #newBuffer

def deleteTmpFile(filepath):
    if os.path.exists(filepath):
        os.remove(filepath)
    else:
        return

def train(train_data, model_name):
    """Trains learning model associated with a business template"""
    try:
        with db.engine.begin() as connection:
            data['vendor'] = get_fasttext_labels(model, data['new_description'], 0.75)
        
            # predict vendors
            transactions_simplified = get_fasttext_labels(os.path.join(os.getcwd(), "data", "filex6.bin"), train_data["description"].str.strip(), 0.80)  #predictVendors(transactions_uncleaned, os.path.join(os.getcwd(), "data", "vendors2.joblib"), os.path.join(os.getcwd(), "data","ID_CategoryMap2.joblib"))
           
            # label debit and credit transactions
            vendors_and_transaction_type = transactions_simplified + ' ' +  np.where(train_data['amount'] > 0, 'credit', 'debit')
            
            # train the classifier
            pipeline = Pipeline([
                ('tfidvect', TfidfVectorizer(stop_words='english')),
                ('classifier', RandomForestClassifier(n_estimators=100, random_state=42))
            ])

            pipeline.fit(data['vendor'], data['account'])
        
            # save full pipeline
            dump(pipeline, os.path.join(os.getcwd(),'models', f"{model_name}.joblib"))
    except Exception as e:
        raise