import React, { useState, useEffect  } from "react";

import * as common from "./common"


export function parseTestName(name) {
    let baseName = null;
    let command = null;

    if (name) {
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
            if (spec.length === 3) {
                baseName = spec[2];
                const f = features
                      ? features + ',expensive_tests'
                      : '--features expensive_tests';
                command = 'cargo test -p' + spec[0] + ' --test ' + spec[1] +
                      ' ' + f + ' -- --exact --nocapture ' + spec[2];
            }
            break;
        case 'pytest':
        case 'mocknet':
            baseName = spec[0];
            command = 'cd pytest && python3 tests/' + spec.join(' ');
            break;
        default:
            baseName = spec.join(' ');
            break;
        }
    }

    return {
        testBaseName: baseName,
        testCommand: command && <code>{command}</code>,
    };
}


function testNameWithTimeout(test) {
    if (test.timeout === 180) {
        return test.name;
    }
    const words = test.name.trim().split(/\s+/);
    words.splice(1, 0, '--timeout=' + test.timeout);
    return words.join(' ');
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

    const {testBaseName, testCommand} = parseTestName(aTest && aTest.name);
    common.useTitle(aTest && (testBaseName + ' (run #' + aTest.run_id + ')'));
    const statusCls = aTest && common.statusClassName('text', aTest.status);
    return aTest && <>
        {common.renderBreadCrumbs({
            runId: aTest.run_id,
            buildId: aTest.build_id,
        }, [
            [aTest, aTest.branch],
            [baseBranchHistory, baseBranch],
        ])}
        <table className="big"><tbody>
          {common.commitRow(aTest)}
          <tr><td>Requested by</td><td>{aTest.requester}</td></tr>
          <tr><td>Test</td><td>{testNameWithTimeout(aTest)}</td></tr>
          {testCommand && <tr><td>Command</td><td>{testCommand}</td></tr>}
          {common.formatTimeStatsRows(aTest)}
          <tr><td>Status</td><td className={statusCls}>{aTest.status}</td></tr>
          {aTest.logs ? <>
             <tr><th colSpan="2">Logs</th></tr>
             {aTest.logs.map(common.logRow)}
           </> : null}
        </tbody></table>
    </>;
}

export default ATest;
