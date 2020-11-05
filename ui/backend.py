from flask import Flask, session, flash, render_template, redirect, json, url_for, request, abort, make_response, jsonify, send_file
import os
from flask_cors import CORS

from ui_db import UIDB

app = Flask(__name__)
CORS(app)

app.config['TEMPLATES_AUTO_RELOAD'] = True


@app.route('/', methods=['GET'])
def get_runs():
    server = UIDB()
    all_runs = server.get_all_runs()
    return jsonify(all_runs)


@app.route('/run', methods=['POST', 'GET'])
def get_a_run():
    request_json = request.get_json(force=True) 
    run_id = request_json['run_id']
    server = UIDB()
    a_run = server.get_one_run(run_id)
    return jsonify(a_run)


@app.route('/test', methods=['POST', 'GET'])
def get_a_test():
    request_json = request.get_json(force=True) 
    test_id = request_json['test_id']
    server = UIDB()
    a_test = server.get_one_test(test_id)
    return jsonify(a_test)


@app.route('/test_history', methods=['POST', 'GET'])
def test_history():
    request_json = request.get_json(force=True) 
    test_id = request_json['test_id']
    server = UIDB()
    history = server.get_test_history_by_id(test_id)
    return jsonify(history)


@app.route('/branch_history', methods=['POST', 'GET'])
def branch_history():
    request_json = request.get_json(force=True) 
    test_id = request_json['test_id']
    branch = request_json['branch']
    server = UIDB()
    history = [server.get_histoty_for_base_branch(test_id, branch)]
    return jsonify(history)

@app.route('/cancel_the_run', methods=['POST', 'GET'])
def cancel_the_run():
    request_json = request.get_json(force=True) 
    run_id = request_json['run_id']
    server = UIDB()
    server.cancel_the_run(run_id)
    return jsonify({})

@app.route('/get_auth_code', methods=['POST', 'GET'])
def get_auth_code():
    request_json = request.get_json(force=True) 
    login = request_json['github_login']
    server = UIDB()
    code = server.get_auth_code(login)
    return jsonify({"code": code})


if __name__ == '__main__':
    app.run(debug=True, host="0.0.0.0", port=5005)
    
