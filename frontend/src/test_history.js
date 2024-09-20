import React , { useState, useEffect  } from "react";

import * as common from "./common";
import {parseTestName} from "./a_test";


const baseBranch = 'master';


/** Formats page title base on data returned by the back end. */
function formatTitle(data, testId) {
    let title = parseTestName(data).testBaseName;
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
                    .then(data => void setBaseBranchHistory(data));
            } else {
                setBaseBranchHistory(null);
            }
        });
    }, [props.match.params.test_id]);

    const formatRow = a_test => {
        const timeStats = common.formatTimeStats(a_test);
        return <tr key={a_test.test_id}>
          <td>{common.branchLink(a_test)}</td>
          <td>{common.formatRequester(a_test.requester)}</td>
          <td>{common.commitNavLink('/test/' + a_test.test_id, a_test.title)}</td>
          <td className={common.statusClassName('text', a_test.status)}>{a_test.status}
            {a_test.status === 'PASSED' && a_test.tries > 1 && (
                  <small>  {a_test.tries}</small>
            )}</td>
          <td>{common.allLogLinks(a_test.logs, a_test.test_id)}</td>
          <td>{timeStats.delta}</td>
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
          <th>Requester</th>
          <th>Title</th>
          <th>Status</th>
          <th>Logs</th>
          <th>Run Time</th>
          <th>Finished</th>
        </tr>
      </thead><tbody>
       {currentBranchHistory.tests.map(formatRow)}
      </tbody></table>
    </>;
}

export default TestHistory;
