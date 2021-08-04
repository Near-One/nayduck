import React , { useState, useEffect  } from "react";
import {
    NavLink,
  } from "react-router-dom";

import {RenderHistory, StatusColor, fetchApi, GitRepo} from "./common"

function ATest (props) {
    const [aTest, setATest] = useState([]);
    const [baseBranchHistory, setBaseBranchHistory] = useState([]);
    const baseBranch = "master";

    useEffect(() => {
        const basePath = '/test/' + (0 | props.match.params.test_id);
        fetchApi(basePath)
            .then(data => setATest(data));
        fetchApi(basePath + '/history/' + baseBranch)
            .then(data => setBaseBranchHistory(data));
    }, [props.match.params.test_id]);

    return (
    <div>
      {aTest.map((a_test,i) =>
        <div>
        <table style={{"border" : "0px", "width": "40%"}}> <tbody>
          <tr><td style={{"border": "0px"}}><NavLink to={"/run/" + a_test.run_id}> Back To A Run</NavLink></td>
          <td style={{"border": "0px", "font-size":"10px"}}>{RenderHistory(a_test, ("This test history for branch " + a_test.branch))}</td>
          {baseBranch === a_test.branch ? (null) :
          baseBranchHistory.map((base_test,j) => <td style={{"border": "0px", "font-size":"10px"}}>{RenderHistory(base_test, ("This test history for branch " + baseBranch))}</td>)
          }
          </tr>
        </tbody></table>
        <br/><br/>
        <table className="big"><tbody>
            <tr><td style={{"width":"20%"}}>Commit</td><td>
            {a_test.branch} (<a href={GitRepo()+"/commit/"+a_test.sha}>{a_test.sha.slice(0,7)}</a>)<br/>
            {a_test.title}<br/>
             requested by {a_test.requester}
            </td></tr>
            <tr><td>Test</td><td>{a_test.cmd}</td></tr>
            <tr><td>Run Time</td><td>{a_test.run_time}</td></tr>
            <tr><td>Finished</td><td>{a_test.finished}</td></tr>
            <tr><td>Started</td><td>{a_test.started}</td></tr>
            <tr><td>Status</td><td style={{"color": StatusColor(a_test.status)}}>{a_test.status}</td></tr>
        </tbody></table>
        <table><tbody>
        {Object.entries(a_test.logs).map( ([key, value]) =>

        <tr><td style={{"width":"20%"}}>
            <a style={{"color": value.stack_trace ? "red" :
                  String(value.patterns).includes("LONG DELAY") ? "orange" : "blue"}} href={value.storage}>{key}</a></td>
            <td><textarea style={{"width":"100%", "height": "300px"}}>{value.log}</textarea></td></tr>

        )}
        </tbody></table>
        </div>
        )}
    </div>
    );
}

export default ATest;
