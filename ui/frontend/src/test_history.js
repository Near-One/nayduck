import React , { useState, useEffect  } from "react";
import {
    NavLink,
  } from "react-router-dom";
import {RenderHistory, fetchApi, GitRepo} from "./common"


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
        const basePath = '/test/' + (0 | props.match.params.test_id);
        fetchApi(basePath + '/history')
            .then(data => {
                setHistory(data);
                const branch = data[0]["branch"];
                if (branch) {
                    setCurrentBranch(branch);
                    fetchApi(basePath + '/history/' + branch)
                        .then(data => setCurrentBranchHistory(data));
                }
            });
        fetchApi(basePath + '/history/' + baseBranch)
            .then(data => setBaseBranchHistory(data))
    }, []);

    return (
      <div>
        <table style={{"border" : "0px", "width": "40%"}}> <tbody><tr>
          {currentBranchHistory.map((current_test,j) =>
          <td style={{"border": "0px", "font-size":"10px"}}>{
            RenderHistory(current_test, ("This test history for branch " + currentBranch))}</td>)}
          {baseBranch === currentBranch ? (null) :
            baseBranchHistory.map((base_test,j) =>
            <td style={{"border": "0px", "font-size":"10px"}}>{RenderHistory(base_test, ("This test history for branch " + baseBranch))}</td>)
          }
        </tr></tbody></table>
        <table  className="big"><tbody>
          <tr>
            <th>Commit</th>
            <th style={{"width": "40%"}}>Title</th>
            <th>Status</th>
            <th>Logs</th>
            <th>Run Time</th>
            <th>Started</th>
            <th>Finished</th>
        </tr>
        {history.map((a_test,i) =>
            <tr key={a_test.test_id}>
            <td>{a_test.branch} (<a href={GitRepo()+"/commit/"+a_test.sha}>{a_test.sha.slice(0,7)}</a>)<br/>
            </td>
            <td> <NavLink to={"/test/" + a_test.test_id} >{a_test.title}</NavLink></td>
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
