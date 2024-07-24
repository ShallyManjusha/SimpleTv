from flask import Flask, request, jsonify
from ibm_watson_machine_learning.foundation_models import Model
from ibm_watson import DiscoveryV2
from ibm_cloud_sdk_core.authenticators import IAMAuthenticator
from sentence_transformers import SentenceTransformer
from dotenv import load_dotenv
import os
import json
from rerankers import Reranker

load_dotenv()

app = Flask(__name__)

IBM_APIKEY = str(os.environ.get("IBM_APIKEY"))
Project_id = str(os.environ.get("Project_id"))
WD_APIKEY = str(os.environ.get("WD_APIKEY"))
wd_project_id = str(os.environ.get("WD_Project_ID"))
collection_id = str(os.environ.get("WD_Collection_ID"))

def get_credentials():
    return {
        "url": "https://us-south.ml.cloud.ibm.com",
        "apikey": IBM_APIKEY
    }

model_id = "mistralai/mixtral-8x7b-instruct-v01"
parameters = {
    "decoding_method": "greedy",
    "max_new_tokens": 200,
    "stop_sequences": ["#"],
    "repetition_penalty": 1
}
foundation_model = Model(
    model_id=model_id,
    params=parameters,
    credentials=get_credentials(),
    project_id=Project_id
)

authenticator = IAMAuthenticator(WD_APIKEY)
discovery = DiscoveryV2(
    version='2023-03-31',
    authenticator=authenticator
)
discovery.set_service_url("https://api.au-syd.discovery.watson.cloud.ibm.com/instances/7a2fee62-0789-428a-84a2-1b04c237aaeb")
discovery.set_disable_ssl_verification(True)

collections = discovery.list_collections(project_id=wd_project_id).get_result()

parameters["stop_sequences"] = ["}"]
foundation_model_entity = Model(
    model_id=model_id,
    params=parameters,
    credentials=get_credentials(),
    project_id=Project_id
)

ranker = Reranker("colbert", lang="es")

def get_entities(question):
    json_prompt_v1={
"channel": "",
"program": "El ultimó camino,Brunch con Bobby Flay"
}
    json_prompt_v2={
    "channel": "espn 2",
    "program": "la dimensión desconocida"
    }
    entity_prompt=f"""

    You are given a query in Spanish for a cable tv service provider called SimpleTv that is asking information about the channel or the programs on that channel.

    Extract the channel name and the program name if any in the query and return the results in json format
    Do not generate additional questions and only generate what is asked

    Question : ¿En qué canal puedo ver El ultimó camino y Brunch con Bobby Flay?

    Output : 
    {json.dumps(json_prompt_v1)}

    Question : ¿puedo ver la dimensión desconocida en espn 2 si tengo el curso adecuado?

    Output : 
    {json.dumps(json_prompt_v2)}

    Question :{question}
    Output:

    """
    #using the entity and channel, fetch only those documents with channel as cartoon network
    print("Submitting generation request...")
    generated_response = foundation_model_entity.generate_text(prompt=entity_prompt, guardrails=False)
    print(generated_response)
    json_response=json.loads(generated_response)
    return json_response

def get_files_from_discovery(json_response,question):
    files=[]
    print(json_response)
    if ("program" in json_response and json_response["program"]!="") or ("channel" in json_response and json_response["channel"]!=""):
        print("In JR")
        program= json_response["program"] if "program" in json_response else ""
        channel= json_response["channel"] if "channel" in json_response else ""
        if len(channel.split(","))>1:
            for i in channel.split(","):
                response = discovery.query(
                project_id=wd_project_id,
                collection_ids = ['104f3a09-5c1e-3998-0000-0190ca5e491d','ba71af88-0dd6-8965-0000-0190ca2fb33a'],
                natural_language_query="text:"+i+","+program,
                highlight= False,
                count=3).get_result()
                # print("Serach Discovery",response)
                for d in response["results"]:
                    if(d["result_metadata"]["confidence"]>0.05):
                        files.append(d["text"])
        else:
            print("In else")
            response = discovery.query(
                project_id=wd_project_id,
                collection_ids = ['104f3a09-5c1e-3998-0000-0190ca5e491d','ba71af88-0dd6-8965-0000-0190ca2fb33a'],
                natural_language_query="text:"+channel+","+program,
                highlight= False,
                count=10).get_result()
            # print("Serach Discovery",response)
            for d in response["results"]:
                    if(d["result_metadata"]["confidence"]>0.05):
                        files.append(d["text"])
            results = ranker.rank(query=question, docs=[json.dumps(i) for i in files]).top_k(3)
            results=[i.text for i in results]
    else:
        print("else",question)
        response = discovery.query(
                project_id=wd_project_id,
                collection_ids = ['104f3a09-5c1e-3998-0000-0190dae46b2e'],
                natural_language_query="question:"+question,
                highlight= False,
                count=10).get_result()
        print("Serach Discovery",response)
        for d in response["results"]:
                    if(d["result_metadata"]["confidence"]>0.03):
                        files.append(d["text"])
    return files

def filter_files(json_response,files):
    print("Files",files)
    files_new=[]

    if "program" in json_response and  json_response["program"]=="" :
            print("In if")
            for f in files:
                f=json.loads(f[0])
                del f['Programs']
                # f['Programs']=",".join([program["ProgramTitle"] for program in f["Programs"]])
                files_new.append(f)
    elif  "program" in json_response and json_response["program"]!="" :
            print("In elsif")
            for i in files:
                i=json.loads(i[0])
                i["Programs"]=list(filter(lambda x:fuzz.token_set_ratio(x["ProgramTitle"].lower(),json_response["program"].lower().strip())>=70,i["Programs"]))
                print(i["Programs"])
                files_new.append(i)
    elif "channel" in json_response and  json_response["channel"]!="":
        for f in files:
                f=json.loads(f[0])
                del f['Programs']
                # f['Programs']=",".join([program["ProgramTitle"] for program in f["Programs"]])
                files_new.append(f)
         
    else:
        print("In else")
        files_new=files
    return files_new

def search_query(question):
    #get entities
    
    json_response=get_entities(question)
    print("-----",json_response)
    files=get_files_from_discovery(json_response,question)
    print("Search_Query",files)
    # print("type",type(jso))
    if ("program" in json_response and json_response["program"]!="") or ("channel" in json_response and json_response["channel"]!=""):
        files_new=filter_files(json_response,files)
        
    else:
        files_new=files
    print("Filtered_Files",files_new)
    results = ranker.rank(query=question, docs=[json.dumps(i) for i in files_new]).top_k(len(json_response["channel"].split(","))+2)
    results=[i.text for i in results]
    print(len(results))
    prompt_input = f"""
    Given the context of a tv network provider enlisting the channels and the programs list in json. 
    Analyze the context and answer the question in spanish. 
    If you don't know the answer to a question, please don't share false information. Do not provide any extra information. Do not include the input in the answer

    Input: Question: {question}
    Context : {json.dumps(results)}

    Output:"""
    print("Submitting generation request...")
    generated_response = foundation_model.generate_text(prompt=prompt_input, guardrails=False)
    print(generated_response)
    return generated_response

@app.route('/')
def health_check():
    return jsonify({"status": "Connection successful"}), 200

@app.route('/search_query', methods=['POST'])
def handle_search_query():
    data = request.get_json()
    question = data.get('question')
    if not question:
        return jsonify({"error": "Question is required"}), 400
    try:
        response = search_query(question)
        return jsonify(response), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)
