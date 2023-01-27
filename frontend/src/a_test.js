import React, { useState, useEffect  } from "react";

import * as common from "./common"


export function parseTestName(test) {
    if (!test || !test.name) {
        return {
            testBaseName: null,
            testCommand: null,
        };
    }

    const spec = test.name.trim().split(/\s+/);
    const category = spec[0];
    const pos = spec.indexOf('--features');
    const featuresArray = pos !== -1 ? spec.splice(pos) : [];
    const features = featuresArray.length > 0
          ? ' ' + featuresArray.join(' ') + ',test_features'
          : ' --features test_features';
    const additionalBinariesFeatures = featuresArray.includes("nightly")
        ? '--features nightly '
        : ' ';
    let release = '';
    let i = 1;
    for (; /^--/.test(spec[i] || ''); ++i) {
        if (spec[i] === '--release') {
            release = ' --release';
        }
    }
    spec.splice(0, i);

    let baseName = null;
    let command = null;
    switch (category) {
    case 'expensive':
        if (spec.length === 3) {
            baseName = spec[2];
            command = 'cargo test -p' + spec[0] + release + features +
                ',expensive_tests -- --exact --nocapture ' + spec[2];
            command = <code>{command}</code>;
        }
        break;
    case 'pytest':
    case 'mocknet':
        baseName = spec[0] === 'fuzz.py' ? spec.slice(1, 3).join(' ') : spec[0];
        command = 'python3 pytest/tests/' + spec.join(' ');
        command = test.skip_build ? <code>{command}</code> : <code>
          <small>cargo build {release} -pneard {features},rosetta_rpc &amp;&amp;</small><br/>
          <small>cargo build {release} -pgenesis-populate -prestaked -pnear-test-contracts {additionalBinariesFeatures}&amp;&amp;</small><br/>
          {command}
        </code>;
        break;
    default:
        baseName = spec.join(' ');
        break;
    }

    return {
        testBaseName: baseName,
        testCommand: command,
    };
}


function formatFullTestName(test) {
    let {name, timeout, skip_build} = test;
    if (timeout === 180 && !skip_build) {
        return name;
    }
    const args = [1, 0];
    if (skip_build) {
        args.push('--skip-build');
    }
    if (timeout !== 180) {
        if (timeout % 3600 === 0) {
            timeout = (timeout / 3600) + 'h';
        } else if (timeout % 60 === 0) {
            timeout = (timeout / 60) + 'm';
        }
        args.push('--timeout=' + timeout);
    }
    const words = test.name.trim().split(/\s+/);
    Array.prototype.splice.apply(words, args);
    return words.join(' ');
}


function nth(n) {
    const unit = n % 10;
    if (unit === 1 && n % 100 !== 11) {
        return n + 'st';
    } else if (unit === 2 && n % 100 !== 12) {
        return n + 'nd';
    } else if (unit === 3 && n % 100 !== 13) {
        return n + 'rd';
    } else {
        return n + 'th';
    }
}


function formatTriesCount(test) {
    const body = (() => {
        if (!test || !test.tries) {
            return null;
        }
        const count = 0 | test.tries;
        switch (test.status) {
        case 'PENDING':
            return count + ' failed ' + (count === 1 ? 'try' : 'tries');
        case 'RUNNING':
            return count > 1 ? nth(count) + ' try' : null;
        default:
            return count > 1 ? count + ' tries' : null;
        }
    })();
    return body && <small>  ({body})</small>;
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

    const gitBisectCommand = aTest && aTest.first_bad && aTest.last_good ?
        <div><code><small>
            git bisect start {aTest.first_bad.substr(0, 8)} {aTest.last_good.substr(0, 8)}
        </small></code></div> : null;

    const {testBaseName, testCommand} = parseTestName(aTest);
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
          <tr>
            <td>Requested by</td>
            <td>{common.formatRequester(aTest.requester)}</td>
          </tr>
          <tr><td>Test</td><td>{formatFullTestName(aTest)}</td></tr>
          {testCommand && <tr><td>Command</td><td>{testCommand}</td></tr>}
          {common.formatTimeStatsRows('Run Time', aTest)}
          <tr>
            <td>Status</td>
            <td><span className={statusCls}>{aTest.status}</span>
                {formatTriesCount(aTest)}
                {gitBisectCommand}</td>
          </tr>
          {aTest.logs ? <>
             <tr><th colSpan="2">Logs</th></tr>
             {aTest.logs.map(common.logRow)}
           </> : null}
        </tbody></table>
    </>;
}

export default ATest;
