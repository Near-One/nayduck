import React, { useState, useEffect  } from "react";
import { NavLink } from "react-router-dom";

import * as common from "./common"


function ATest (props) {
    const [aTest, setATest] = useState(null);
    const [baseBranchHistory, setBaseBranchHistory] = useState([]);
    const baseBranch = "master";

    useEffect(() => {
        const basePath = '/test/' + (0 | props.match.params.test_id);
        common.fetchAPI(basePath).then(setATest);
        common.fetchAPI(basePath + '/history/' + baseBranch)
            .then(setBaseBranchHistory);
    }, [props.match.params.test_id]);

    if (!aTest) {
        return null;
    }

    const timeStats = common.formatTimeStats(aTest);
    return (
      <>
        <table style={{border: 0, width: "40%"}}><tbody>
          <tr><td style={{border: 0}}><NavLink to={"/run/" + aTest.run_id}> Back To A Run</NavLink></td>
          <td style={{border: 0, fontSize: "10px"}}>{common.RenderHistory(aTest, ("This test history for branch " + aTest.branch))}</td>
          {baseBranch === aTest.branch ? (null) :
          baseBranchHistory.map((base_test,j) => <td style={{border: 0, fontSize: "10px"}}>{common.RenderHistory(base_test, ("This test history for branch " + baseBranch))}</td>)
          }
          </tr>
        </tbody></table>
        <table className="big"><tbody>
          <tr>
              <td>Commit</td>
              <td>{common.commitLink(aTest)} {aTest.title}</td>
           </tr>
          <tr><td>Requested by</td><td>{aTest.requester}</td></tr>
          <tr><td>Test</td><td>{aTest.cmd}</td></tr>
          <tr><td>Run Time</td><td>{timeStats.delta}</td></tr>
          <tr><td>Finished</td><td>{timeStats.finished}</td></tr>
          <tr><td>Started</td><td>{timeStats.started}</td></tr>
          <tr><td>Status</td><td style={{color: common.testStatusColour(aTest.status)}}>{aTest.status}</td></tr>
          <tr><th colSpan="2">Logs</th></tr>
          {aTest.logs.map(log =>
            <tr key={aTest.test_id + '/' + log.type}>
              <td>{common.logLink(log)}</td>
              <td>{common.logBlob(log.log)}</td></tr>
          )}
        </tbody></table>
      </>
    );
}

export default ATest;
