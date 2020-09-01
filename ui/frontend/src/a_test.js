import React , { useState, useEffect  } from "react";
import {
    NavLink,
  } from "react-router-dom";

import {RenderHistory, StatusColor, ServerIp, GitRepo} from "./common"

function ATest (props) {
    const [aTest, setATest] = useState([]);
    const [baseBranchHistory, setBaseBranchHistory] = useState([]);
    const baseBranch = "master";
  
    useEffect(() => {

        fetch(ServerIp() + '/test', {
          headers : { 
            'Content-Type': 'application/json',
            'Accept': 'application/json'
           },
           method: 'POST',
           body: JSON.stringify({'test_id': props.match.params.test_id}),
          }).then((response) => response.json())
          .then(data => {
          setATest(data);
          console.log(data);
          
        });
        fetch(ServerIp() + '/branch_history', {
          headers : { 
            'Content-Type': 'application/json',
            'Accept': 'application/json'
           },
           method: 'POST',
           body: JSON.stringify({'test_id': props.match.params.test_id, 'branch': baseBranch}),
          }).then((response) => response.json())
          .then(data => {
          setBaseBranchHistory(data);
          console.log(data);
        });
    }, []);

    return (
    <div>
      {aTest.map((a_test,i) =>
        <div>
          <table style={{"border" : "0px", "width": "40%"}}> <tbody>
        <tr><td style={{"border": "0px"}}><NavLink to={"/run/" + a_test.run_id}> Back To Run</NavLink></td>
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
            <tr><td>Test</td><td>{a_test.name}</td></tr>
            <tr><td>Run Time</td><td>{a_test.run_time}</td></tr>
            <tr><td>Test Time</td><td>{a_test.test_time}</td></tr>
            <tr><td>Finished</td><td>{a_test.finished}</td></tr>
            <tr><td>Started</td><td>{a_test.started}</td></tr>
            <tr><td>Status</td><td style={{"color": StatusColor(a_test.status)}}>{a_test.status}</td></tr>
        </tbody></table>
        <table><tbody>
        {Object.entries(a_test.logs).map( ([key, value]) =>
        
        <tr><td style={{"width":"20%"}}>
            <a style={{"color": value.stack_trace ? "red" : "blue"}} href={value.storage}>{key}</a></td>
            <td><textarea style={{"width":"100%", "height": "300px"}}>{value.log}</textarea></td></tr> 
        
        )}
        </tbody></table>
        </div>
        )}  
    </div>
    );
}
 
export default ATest;
