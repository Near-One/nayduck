import React , { useState, useEffect  } from "react";
import { NavLink } from "react-router-dom";

import * as common from "./common";


function TestHistory (props) {
    const [history, setHistory] = useState(null);
    const [baseBranchHistory, setBaseBranchHistory] = useState(null);
    const [currentBranchHistory, setCurrentBranchHistory] = useState(null);
    const baseBranch = "master";
    const [currentBranch, setCurrentBranch] = useState("");

    useEffect(() => {
        const basePath = '/test/' + (0 | props.match.params.test_id);
        common.fetchAPI(basePath + '/history').then(data => {
            if (!data) {
                setHistory(null);
                setCurrentBranch('');
                setCurrentBranchHistory(null);
                setBaseBranchHistory(null);
                return;
            }
            data.test_id = (0 | props.match.params.test_id);
            setHistory(data.tests);
            setCurrentBranch(data.branch);
            setCurrentBranchHistory(data);
            if (data.branch !== baseBranch) {
                common.fetchAPI(basePath + '/history/' + baseBranch)
                    .then(data => {
                        data.test_id = (0 | props.match.params.test_id);
                        setBaseBranchHistory(data)
                    });
            } else {
                setBaseBranchHistory(null);
            }
        });
    }, [props.match.params.test_id]);

    const formatRow = a_test => {
        const timeStats = common.formatTimeStats(a_test);
        return (
          <tr key={a_test.test_id}>
            <td>{common.commitLink(a_test)}</td>
            <td><NavLink to={"/test/" + a_test.test_id} >{a_test.title}</NavLink></td>
            <td style={{color: common.testStatusColour(a_test.status)}}>{a_test.status}</td>
            <td>{common.allLogLinks(a_test.logs, a_test.test_id)}</td>
            <td>{timeStats.delta}</td>
            <td>{timeStats.started}</td>
            <td>{timeStats.finished}</td>
          </tr>
        );
    }

    return history ? (
      <>
        <table style={{border: 0, width: "40%"}}><tbody><tr>
          {common.renderHistoryCell(currentBranchHistory, currentBranch)}
          {common.renderHistoryCell(baseBranchHistory, baseBranch)}
        </tr></tbody></table>
        <table className="big"><thead>
          <tr>
            <th>Commit</th>
            <th>Title</th>
            <th>Status</th>
            <th>Logs</th>
            <th>Run Time</th>
            <th>Started</th>
            <th>Finished</th>
          </tr>
        </thead><tbody>
         {history.map(formatRow)}
        </tbody></table>
      </>
    ) : null;
}

export default TestHistory;
