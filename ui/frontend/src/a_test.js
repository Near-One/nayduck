import React, { useState, useEffect  } from "react";
import { NavLink } from "react-router-dom";

import * as common from "./common"


function ATest (props) {
    const [aTest, setATest] = useState([]);
    const [baseBranchHistory, setBaseBranchHistory] = useState([]);
    const baseBranch = "master";

    useEffect(() => {
        const basePath = '/test/' + (0 | props.match.params.test_id);
        common.fetchAPI(basePath)
            .then(data => setATest(data));
        common.fetchAPI(basePath + '/history/' + baseBranch)
            .then(data => setBaseBranchHistory(data));
    }, [props.match.params.test_id]);

    return (<div>
        {aTest.map((a_test,i) => {
            const timeStats = common.formatTimeStats(a_test);
            return (<div>
                <table style={{"border" : "0px", "width": "40%"}}>
                  <tr><td style={{"border": "0px"}}><NavLink to={"/run/" + a_test.run_id}> Back To A Run</NavLink></td>
                  <td style={{"border": "0px", "font-size":"10px"}}>{common.RenderHistory(a_test, ("This test history for branch " + a_test.branch))}</td>
                  {baseBranch === a_test.branch ? (null) :
                  baseBranchHistory.map((base_test,j) => <td style={{"border": "0px", "font-size":"10px"}}>{common.RenderHistory(base_test, ("This test history for branch " + baseBranch))}</td>)
                  }
                  </tr>
                </table>
                <br/><br/>
                <table className="big">
                    <tr>
                        <td>Commit</td>
                        <td>{common.commitLink(a_test)} {a_test.title}</td>
                     </tr>
                    <tr><td>Requested by</td><td>{a_test.requester}</td></tr>
                    <tr><td>Test</td><td>{a_test.cmd}</td></tr>
                    <tr><td>Run Time</td><td>{timeStats.delta}</td></tr>
                    <tr><td>Finished</td><td>{timeStats.finished}</td></tr>
                    <tr><td>Started</td><td>{timeStats.started}</td></tr>
                    <tr><td>Status</td><td style={{"color": common.StatusColor(a_test.status)}}>{a_test.status}</td></tr>
                    {a_test.logs.map(log =>
                        <tr><td>{common.logLink(log)}</td>
                        <td><textarea style={{"width":"100%", "height": "300px"}}>{log.log}</textarea></td></tr>
                    )}
                </table>
            </div>);
        })}
    </div>);
}

export default ATest;
