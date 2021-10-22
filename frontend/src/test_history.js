import React , { useState, useEffect  } from "react";
import { NavLink } from "react-router-dom";

import * as common from "./common";
import {parseTestName} from "./a_test";


const baseBranch = 'master';


/** Formats page title base on data returned by the back end. */
function formatTitle(data, testId) {
    let title = parseTestName(data && data.name).testBaseName;
    title = title || ('Test #' + testId);
    title += ' (history';
    if (data && data.branch !== baseBranch) {
        title += ' on branch ' + data.branch;
    }
    return title + ')';
};


function TestHistory (props) {
    const [currentBranchHistory, setCurrentBranchHistory] = useState(null);
    const [baseBranchHistory, setBaseBranchHistory] = useState(null);

    useEffect(() => {
        const basePath = '/test/' + (0 | props.match.params.test_id);
        common.fetchAPI(basePath + '/history').then(data => {
            if (!data) {
                setCurrentBranchHistory(null);
                setBaseBranchHistory(null);
                return;
            }
            data.test_id = (0 | props.match.params.test_id);
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
        return <tr key={a_test.test_id}>
          <td>{common.commitLink(a_test)}</td>
          <td><NavLink to={"/test/" + a_test.test_id} >{a_test.title}</NavLink></td>
          <td className={common.statusClassName('text', a_test.status)}>{a_test.status}</td>
          <td>{common.allLogLinks(a_test.logs, a_test.test_id)}</td>
          <td>{timeStats.delta}</td>
          <td>{timeStats.started}</td>
          <td>{timeStats.finished}</td>
        </tr>;
    };

    common.useTitle(formatTitle(currentBranchHistory,
                                props.match.params.test_id));
    return currentBranchHistory && <>
      {common.renderBreadCrumbs({testId: props.match.params.test_id}, [
          [currentBranchHistory, currentBranchHistory.branch],
          [baseBranchHistory, baseBranch],
      ])}
      <table className="big list"><thead>
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
       {currentBranchHistory.tests.map(formatRow)}
      </tbody></table>
    </>;
}

export default TestHistory;
