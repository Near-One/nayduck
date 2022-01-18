import React, { useState, useEffect  } from "react";
import { NavLink } from "react-router-dom";

import * as common from "./common";


const testStatusKeys = {
    'FAILED': 1,
    'CHECKOUT FAILED': 2,
    'SCP FAILED': 3,
    'TIMEOUT': 4,
    'PASSED': 5,
    'IGNORED': 6,
    'CANCELED': 7,
    'RUNNING': 8,
    'PENDING': 9,
};


/** Processes run data received from the back end.
 *
 * For each test in the run parses its name to extract properties such as set of
 * features and whether release or dev build was used.  Furthermore, calculates
 * run’s finish time and collects statistics about test statuses.
 *
 * Modifies `run` in place.
 */
const processRun = run => {
    if (!run) {
        return;
    }

    const statuses = Object.create(null);
    let notFinished = false;
    let finished = run.timestamp;

    run.tests.forEach(test => {
        const words = test.name.split(/ +/);

        test.features = '';
        let pos = words.indexOf('--features');
        if (pos !== -1) {
            test.features = words.splice(pos + 1).join(' ');
            words.pop();
        }

        test.is_release = false;
        pos = words.indexOf('--release');
        if (pos !== -1) {
            test.is_release = true;
            words.splice(pos, 1);
        }

        pos = words.indexOf('--remote');
        if (pos !== -1) {
            words.splice(pos, 1);
        }

        test.name = words.join(' ');

        let short_name;
        switch (words[0]) {
        case 'pytest':
        case 'mocknet':
            short_name = words[1];
            if (short_name === 'fuzz.py' && words.length >= 4) {
                short_name = words.splice(2, 2).join(' ');
                short_name = <><small>fuzz.py</small> {short_name}</>;
            }
            if (words.length > 2) {
                words.splice(0, 2);
                short_name = <>{short_name} <small>{words.join(' ')}</small></>;
            }
            break;
        case 'expensive':
            // "expensive" <package> <binary> <test> <args>...
            const pkg = words[1];
            const test = words[3]
                .replace(/^tests?::/, '')
                .replace(/^([A-Za-z0-9_]*)::tests?::/, '$1 ')
            words.splice(0, 4);
            short_name = words.length
                ? <><small>{pkg}</small> {test} <small>{words.join(' ')}</small></>
                : <><small>{pkg}</small> {test}</>
            break;
        default:
            /* nop */;
        }
        test.short_name = short_name
            ? <span title={test.name}>{short_name}</span>
            : test.name;

        const status = test.status;
        statuses[test.status] = (statuses[test.status] || 0) + 1;
        if (status === 'PENDING' || status === 'RUNNING') {
            notFinished = true;
        } else if (finished == null || test.finished > finished) {
            finished = test.finished;
        }
    });

    run.started = run.timestamp;
    if (!notFinished) {
        run.finished = finished;
    }
    run.statuses = Object.entries(statuses).sort((a, b) => {
        const aIdx = testStatusKeys[a[0]] || 10;
        const bIdx = testStatusKeys[b[0]] || 10;
        return aIdx - bIdx;
    });
};


/** Formats list of features for display. */
const formatFeatures = feataures => {
    return feataures === 'nightly_protocol,nightly_protocol_features'
        ? <i title="nightly_protocol,nightly_protocol_features">nightly</i>
        : feataures;
};


/** Filters tests based on criteria in the filter form.
 *
 * Returns filtered array of tests.  `tests` is not modified though if no
 * filters were applied return value may be the same array as `tests`.
 */
const filterTests = tests => {
    const getValue = id => document.getElementById(id).value.toLowerCase();
    let value = getValue('build_fltr');
    let filtered = value === 'dev' || value === 'rel'
        ? tests.filter(item => (value === 'dev') === !item.is_release)
        : tests;
    value = getValue('features_fltr');
    filtered = value
        ? filtered.filter(item => value === ' '
                          ? !item.features
                          : item.features.toLowerCase().includes(value))
        : filtered;
    value = getValue('name_fltr');
    filtered = value
        ? filtered.filter(item => item.name.toLowerCase().includes(value))
        : filtered;
    value = getValue('status_fltr');
    filtered = value
        ? filtered.filter(item => item.status.toLowerCase().includes(value))
        : filtered;
    return filtered;
};


/** Returns a comparator function comparing run-time of two test objects.
 *
 * More specifically, returns a function which looks at argument’s `started` and
 * `finished` proprieties.  Objects with no `finished` property are assumed to
 * run until now and objects with no `started` property are assumed to have
 * negative run time.
 *
 * If `desc` argument is `true` comparator sorts objects with biggest run time
 * first; otherwise it sorts objects with lowest run time first.
 */
const makeDeltaComparator = desc => {
    const pos = desc ? -1 : 1;
    return (a, b) => {
        const aDelta = common.getTimeDelta(a, -1);
        const bDelta = common.getTimeDelta(b, -1);
        if (aDelta === bDelta) {
            return 0;
        } else {
            return aDelta < bDelta ? -pos : pos;
        }
    };
};


/** Returns a row with formatted test statuses. */
const formatStatusRow = statuses => {
    return statuses.length ? <tr><td>Status</td><td>{
        statuses.map((entry, idx) => {
            const [status, count] = entry;
            return <React.Fragment key={idx}>{
                idx ? ' / ' : null
            }<span class={common.statusClassName('text', status)}>{status}:
             {count}</span></React.Fragment>
        })
    }</td></tr> : null;
};


/** Formats page title for the run. */
const formatTitle = aRun => {
    if (!aRun) {
        return null;
    } else if (aRun.requester === 'NayDuck') {
        return 'Nightly ' + common.formatDateTime(aRun.started).substr(0, 10);
    } else {
        let title = 'Run #' + aRun.run_id;
        if (aRun.branch !== 'master') {
            title += ' on ' + aRun.branch;
        }
        return title + ' by ' + aRun.requester;
    }
};


function ARun (props) {
    const [orderDescTestTime, setOrderDescTestTime] = useState(true);
    const [aRun, setARun] = useState(null);
    const [filteredRuns, setFilteredRuns] = useState([])

    useEffect(() => {
        let run_id = props.match.params.run_id;
        if (run_id !== 'nightly') {
            run_id = 0 | run_id;
        }
        common.fetchAPI('/run/' + run_id)
            .then(data => {
                if (data) {
                    processRun(data);
                }
                setARun(data);
                setFilteredRuns(data ? data.tests : []);
            });
    }, [props.match.params.run_id]);

    const filterByAll = event => {
        setFilteredRuns(filterTests(aRun.tests));
    }

    const orderByTestTime = event => {
        if (aRun) {
            const cmp = makeDeltaComparator(orderDescTestTime);
            aRun.tests.sort(cmp);
            filteredRuns.sort(cmp);
            setARun(aRun);
            setFilteredRuns(filteredRuns);
        }
        setOrderDescTestTime(!orderDescTestTime);
    };

    common.useTitle(formatTitle(aRun));
    return aRun && <>
      {common.renderBreadCrumbs()}

      <table className="big"><tbody>
        {common.commitRow(aRun)}
        <tr>
          <td>Requested by</td>
          <td>{common.formatRequester(aRun.requester)}</td>
        </tr>
        {common.formatTimeStatsRows('Run Time', aRun)}
        {formatStatusRow(aRun.statuses)}
      </tbody></table>

      <table className="big list"><thead>
        <tr>
          <th>Build
          <select onChange={filterByAll} id="build_fltr">
            <option value=" ">(all)</option>
            <option value="dev">Dev</option>
            <option value="rel">Release</option>
          </select>
          </th>
          <th>Features <input id="features_fltr" onChange={filterByAll}/></th>
          <th>Test <input id="name_fltr" onChange={filterByAll} /></th>
          <th>Status <input id="status_fltr" onChange={filterByAll} /></th>
          <th>Logs</th>
          <th>Run Time <button onClick={orderByTestTime}>↕</button></th>
          <th>Started</th>
          <th>Finished</th>
        </tr>
      </thead><tbody className="with-features">
      {filteredRuns.map(a_test => {
          const timeStats = common.formatTimeStats(a_test);
          const statusCls = common.statusClassName(
              'text', a_test.status);
          return (
            <tr key={a_test.test_id}>
              <td>{a_test.is_release ? 'Release' : 'Dev'}</td>
              <td>{formatFeatures(a_test.features)}</td>
              <td><NavLink to={"/test/" + a_test.test_id}>{a_test.short_name}</NavLink></td>
              <td className={statusCls}>{a_test.status}<br/>
              {common.renderHistory(a_test)}
              </td>
              <td>{common.allLogLinks(a_test.logs, a_test.test_id)}</td>
              <td>{timeStats.delta}</td>
              <td>{timeStats.started}</td>
              <td>{timeStats.finished}</td>
            </tr>
          );
      })}
      </tbody></table>
    </>;
}

export default ARun;
