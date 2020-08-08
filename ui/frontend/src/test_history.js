import React , { useState, useEffect  } from "react";
import {
    NavLink,
  } from "react-router-dom";
import {RenderHistory, ServerIp} from "./common"


function status_color(status) {
    switch (status) {
    case "FAILED" || "BUILD FAILED":   return "red";
    case "PASSED":   return "green";
    case "RUNNING":   return "blue";
    case "OTHER":   return "grey";
    default:      return "black";
    }
}

function TestHistory (props) {
    const [history, setHistory] = useState([]);
    const [baseBranchHistory, setBaseBranchHistory] = useState([]);
    const [currentBranchHistory, setCurrentBranchHistory] = useState([]);
    const baseBranch = "master";
    const [currentBranch, setCurrentBranch] = useState("");;

    useEffect(() => {

        fetch(ServerIp() + '/test_history', {
          headers : { 
            'Content-Type': 'application/json',
            'Accept': 'application/json'
           },
           method: 'POST',
           body: JSON.stringify({'test_id': props.match.params.test_id}),
          }).then((response) => response.json())
          .then(data => {
          setHistory(data);
          console.log(data);
          if (data[0]["branch"]) {
            setCurrentBranch(data[0]["branch"]);
            fetch(ServerIp() + '/branch_history', {
            headers : { 
              'Content-Type': 'application/json',
              'Accept': 'application/json'
            },
            method: 'POST',
            body: JSON.stringify({'test_id': props.match.params.test_id, 'branch': data[0]["branch"]}),
            }).then((response) => response.json())
            .then(data => {
              setCurrentBranchHistory(data);
              console.log(data);
          });
        }
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
        <table style = {{"border" : "0px", "width": "40%"}}> <tbody><tr>
          {currentBranchHistory.map((current_test,j) => 
          <td style={{"border": "0px", "font-size":"10px"}}>{
            RenderHistory(current_test, ("This test history for branch " + currentBranch))}</td>)}
          {baseBranch == currentBranch ? (null) : 
            baseBranchHistory.map((base_test,j) =>
            <td style={{"border": "0px", "font-size":"10px"}}>{RenderHistory(base_test, ("This test history for branch " + baseBranch))}</td>)
          }
        </tr></tbody></table>
        <table  className="big"><tbody>
          <tr>
            <th>Commit</th>
            <th style={{"width": "40%"}}>Title</th>
            <th>User</th>
            <th>Status</th>
            <th>Logs</th>
            <th>Run Time</th>
            <th>Started</th>
            <th>Finished</th>
        </tr>
        {history.map((a_test,i) =>
            <tr key={a_test.test_id}>
            <td>{a_test.branch} (<a href={"https://github.com/nearprotocol/nearcore/commit/"+a_test.sha}>{a_test.sha.slice(0,7)}</a>)<br/>
            </td>
            <td> <NavLink to={"/test/" + a_test.test_id} >{a_test.title}</NavLink></td>
            <td>{a_test.user}</td>
            <td style={{"color": status_color(a_test.status)}}>{a_test.status}</td>
            <td>
                {a_test.logs.map((log,j) => 
                <a style={{"color": log.stack_trace ? "red" : "blue"}} href={log.storage}> {log.type + "(" + log.full_size + ")" } </a> 
                )}

             
            </td>
            <td>{a_test.run_time}</td>
            <td>{a_test.started}</td>
            <td>{a_test.finished}</td>
            </tr>  
        )}
        </tbody></table>
      </div>
    );
}
 
export default TestHistory;
