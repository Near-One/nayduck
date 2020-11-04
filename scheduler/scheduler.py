from flask import Flask, session, flash, render_template, redirect, json, url_for, request, abort, make_response, jsonify, send_file
from rc import bash, ok
import requests
import os

from db import SchedulerDB

app = Flask(__name__)

app.config['TEMPLATES_AUTO_RELOAD'] = True

@app.route('/request_a_run', methods=['POST', 'GET'])
def request_a_run():
    request_json = request.get_json(force=True)
    # if not request_json['token']:
    #     resp = {'code': 1, 'response': 'Failure. Your client is too old. NayDuck requires Github auth. Sync your client to head.'}
    #     return jsonify(resp)
    server = SchedulerDB()
    if 'token' in request_json:
        github_login = server.get_github_login(request_json['token'])
        if not github_login:
            resp = {'code': 1, 'response': 'Failure. NayDuck token is not found. Do not try to fake it.'}
            return jsonify(resp)
        elif github_login == "NayDuck":
                allowed = True
        else:
            allowed = False
            github_req = f'''https://api.github.com/users/{github_login}/orgs'''
            response = requests.get(github_req)
            for org in response.json():
                if "login" in org and org['login'] == 'nearprotocol':
                    allowed = True
                    break
            if not allowed:
                resp = {'code': 1, 'response': f'''Failure. {github_login} is not part of NearProtocol org.'''}
                return jsonify(resp)
    if not request_json['branch'] or not request_json['sha']:
        resp = {'code': 1, 'response': 'Failure. Branch and/or git sha were not provided.'}
        return jsonify(resp)

    if 'requester' in request_json:
        requester = request_json['requester']
    else:
        requester = 'unknown'
    
    fetch = bash(f'''
            rm -rf nearcore
            git clone https://github.com/near/nearcore
            cd nearcore
            git fetch 
            git checkout {request_json['sha']}
    ''')
    if fetch.returncode == 0:
        user = bash(f'''
            cd nearcore
            git log --format='%ae' {request_json['sha']}^!
        ''').stdout
        title = bash(f'''
            cd nearcore
            git log --format='%s' {request_json['sha']}^!
        ''').stdout
        tests = []
        for x in request_json['tests']:
                if len(x.strip()) and x[0] != '#':
                    spl = x.split(' ', 1)
                    if spl[0].isnumeric():
                        tests.extend([spl[1]] * int(spl[0]))
                    else:
                        tests.append(x)
        try:
            run_id = server.scheduling_a_run(branch=request_json['branch'],
                                  sha=request_json['sha'],
                                  user=user.split('@')[0],
                                  title=title,
                                  tests=tests,
                                  requester=requester)
        except Exception as e:
            return jsonify({'code': 1, 'response': 'Failure. %s' % str(e)})

        resp = {'code': 0, 'response': 'Success. ' + os.getenv('NAYDUCK_UI') + '/#/run/' + str(run_id)}
    else:
        resp = {'code': 1, 'response': 'Failure. ' + str(fetch.stderr)}
    return jsonify(resp)


if __name__ == '__main__':
    app.run(host='0.0.0.0', debug=True)
    
