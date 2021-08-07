import React , { useState, useEffect  } from "react";
import { NavLink } from "react-router-dom";

import * as common from "./common";


function TestHistory (props) {
    const [history, setHistory] = useState([]);
    const [baseBranchHistory, setBaseBranchHistory] = useState([]);
    const [currentBranchHistory, setCurrentBranchHistory] = useState([]);
    const baseBranch = "master";
    const [currentBranch, setCurrentBranch] = useState("");;

    useEffect(() => {
        const basePath = '/test/' + (0 | props.match.params.test_id);
        common.fetchAPI(basePath + '/history')
            .then(data => {
                setHistory(data);
                const branch = data[0]["branch"];
                if (branch) {
                    setCurrentBranch(branch);
                    common.fetchAPI(basePath + '/history/' + branch)
                        .then(data => setCurrentBranchHistory(data));
                }
            });
        common.fetchAPI(basePath + '/history/' + baseBranch)
            .then(data => setBaseBranchHistory(data))
    }, [props.match.params.test_id]);

    return (
      <div>
        <table style={{"border" : "0px", "width": "40%"}}> <tbody><tr>
          {currentBranchHistory.map((current_test,j) =>
          <td style={{"border": "0px", "font-size":"10px"}}>{
            common.RenderHistory(current_test, ("This test history for branch " + currentBranch))}</td>)}
          {baseBranch === currentBranch ? (null) :
            baseBranchHistory.map((base_test,j) =>
            <td style={{"border": "0px", "font-size":"10px"}}>{common.RenderHistory(base_test, ("This test history for branch " + baseBranch))}</td>)
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
            <td>{common.commitLink(a_test)}</td>
            <td> <NavLink to={"/test/" + a_test.test_id} >{a_test.title}</NavLink></td>
            <td style={{"color": common.StatusColor(a_test.status)}}>{a_test.status}</td>
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
