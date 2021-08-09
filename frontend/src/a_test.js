import React, { useState, useEffect  } from "react";
import { NavLink } from "react-router-dom";

import * as common from "./common"


function ATest (props) {
    const [aTest, setATest] = useState(null);
    const [baseBranchHistory, setBaseBranchHistory] = useState(null);
    const baseBranch = "master";

    useEffect(() => {
        const basePath = '/test/' + (0 | props.match.params.test_id);
        common.fetchAPI(basePath).then(data => {
            setATest(data);
            if (data && data.branch !== baseBranch) {
                common.fetchAPI(basePath + '/history/' + baseBranch)
                    .then(data => setBaseBranchHistory(data));
            } else {
                setBaseBranchHistory(null);
            }
        });
    }, [props.match.params.test_id]);

    if (!aTest) {
        return null;
    }

    const timeStats = common.formatTimeStats(aTest);
    return (
      <>
        <table claass="nav"><tbody><tr>
          <td><NavLink to={"/run/" + aTest.run_id}>« Back to the run</NavLink></td>
          {common.renderHistoryCell(aTest, aTest.branch)}
          {common.renderHistoryCell(baseBranchHistory, baseBranch)}
        </tr></tbody></table>
        <table className="big"><tbody>
          <tr>
            <td>Commit</td>
            <td>{common.commitLink(aTest)} {aTest.title}</td>
          </tr>
          <tr><td>Requested by</td><td>{aTest.requester}</td></tr>
          <tr><td>Test</td><td>{aTest.name}</td></tr>
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
