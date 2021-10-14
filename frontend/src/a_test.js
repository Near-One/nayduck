import React, { useState, useEffect  } from "react";
import { NavLink } from "react-router-dom";

import * as common from "./common"


function formatTestCommand(name) {
    const spec = name.trim().split(/\s+/);
    const category = spec[0];
    const pos = spec.indexOf('--features');
    const features = pos === -1 ? '' : spec.splice(pos).join(' ');
    let i = 1;
    while (i < spec.length && /^--/.test(spec[i])) {
        ++i;
    }
    spec.splice(0, i);

    switch (category) {
    case 'expensive':
        if (spec.length !== 3) {
            return null;
        }
        const f = features
              ? features + ',expensive_tests'
              : '--features expensive_tests';
        const cmd = 'cargo test -p' + spec[0] + ' --test ' + spec[1] + ' ' + f +
              ' -- --exact --nocapture ' + spec[2];
        return <code>{cmd}</code>;
    case 'pytest':
    case 'mocknet':
        return <code>{'cd pytest && python3 tests/' + spec.join(' ')}</code>;
    default:
        return null;
    }
}


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

    const testCommand = formatTestCommand(aTest.name);
    const timeStats = common.formatTimeStats(aTest);
    const statusCls = common.statusClassName('text', aTest.status);
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
          {testCommand ? <tr><td>Command</td><td>{testCommand}</td></tr> : null}
          <tr><td>Run Time</td><td>{timeStats.delta}</td></tr>
          <tr><td>Finished</td><td>{timeStats.finished}</td></tr>
          <tr><td>Started</td><td>{timeStats.started}</td></tr>
          <tr><td>Status</td><td className={statusCls}>{aTest.status}</td></tr>
          {aTest.logs ? <>
             <tr><th colSpan="2">Logs</th></tr>
             {aTest.logs.map(common.logRow)}
           </> : null}
        </tbody></table>
      </>
    );
}

export default ATest;
