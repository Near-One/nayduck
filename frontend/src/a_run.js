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
        const pos = words.indexOf('--features');
        test.features = pos === -1 ? '' : words.splice(pos).join(' ');
        test.is_release = words.indexOf('--release') !== -1;
        test.name = words.filter(word => !word.startsWith('--')).join(' ');

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


function ARun (props) {
    const [orderDescTestTime, setOrderDescTestTime] = useState(true);
    const [aRun, setARun] = useState(null);
    const [filteredRuns, setFilteredRuns] = useState([])

    useEffect(() => {
        common.fetchAPI('/run/' + (0 | props.match.params.run_id))
            .then(data => {
                if (data) {
                    processRun(data);
                }
                setARun(data);
                setFilteredRuns(data ? data.tests : []);
            });
    }, [props.match.params.run_id]);

    if (!aRun) {
        return null;
    }

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

    return <>
      {common.renderBreadCrumbs()}

      <table className="big"><tbody>
        <tr>
          <td>Commit</td>
          <td>{common.commitLink(aRun)} {aRun.title}</td>
        </tr>
        <tr><td>Requested by</td><td>{aRun.requester}</td></tr>
        {common.formatTimeStatsRows(aRun)}
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
          const features = (a_test.features || '')
              .replace('--features ', '').replace(/,/, ',​')
          return (
            <tr key={a_test.test_id}>
              <td>{a_test.is_release ? 'Release' : 'Dev'}</td>
              <td>{features}</td>
              <td><NavLink to={"/test/" + a_test.test_id}>{a_test.name}</NavLink></td>
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
