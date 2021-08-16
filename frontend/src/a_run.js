import React, { useState, useEffect  } from "react";
import { NavLink } from "react-router-dom";

import * as common from "./common";


function ARun (props) {
    const [orderDescTestTime, setOrderDescTestTime] = useState(true);
    const [aRun, setARun] = useState([]);
    const [filteredRuns, setFilteredRuns] = useState([])

    const processTest = test => {
        const words = test.name.split(/ +/);
        const pos = words.indexOf('--features');
        test.features = pos === -1 ? '' : words.splice(pos).join(' ');
        test.is_release = words.indexOf('--release') !== -1;
        test.name = words.filter(word => !word.startsWith('--')).join(' ');
    }

    useEffect(() => {
        common.fetchAPI('/run/' + (0 | props.match.params.run_id))
            .then(data => {
                data.forEach(processTest);
                setARun(data);
                setFilteredRuns(data)
            });
    }, [props.match.params.run_id]);

    var filterByAll = event => {
      var fltr = document.getElementById('build_fltr').value.toLowerCase();
      var filtered = fltr === 'dev' || fltr === 'rel'
          ? aRun.filter(item => (fltr === 'dev') === !item.is_release)
          : aRun;
      fltr = document.getElementById('features_fltr').value.toLowerCase();
      filtered = fltr
        ? filtered.filter(item => fltr === ' '
                          ? !item.features
                          : item.features.toLowerCase().includes(fltr))
        : filtered;
      fltr = document.getElementById('name_fltr').value.toLowerCase();
      filtered = fltr
        ? filtered.filter(item => item.name.toLowerCase().includes(fltr))
        : filtered;
      fltr = document.getElementById('status_fltr').value.toLowerCase();
      filtered = fltr
        ? filtered.filter(item => item.status.toLowerCase().includes(fltr))
        : filtered;
      setFilteredRuns(filtered);
    };

    var compareDelta = function(a, b) {
        let aDelta = common.getTimeDelta(a, -1);
        let bDelta = common.getTimeDelta(b, -1);
        if (aDelta === bDelta) {
            return 0;
        } else {
            return aDelta < bDelta ? -1 : 1;
        }
    };

    var orderByTestTime = event => {
        const cmp =
              orderDescTestTime ? compareDelta : (a, b) => -compareDelta(a, b);
        var filtered = [...aRun];
        filtered = filtered.sort(cmp);
        setARun(filtered);
        filtered = [...filteredRuns]
        filtered = filtered.sort(cmp);
        setFilteredRuns(filtered);
        setOrderDescTestTime(!orderDescTestTime);
    };

    return (
      <>
        <table style={{border: 0, width: "40%"}}><tbody>
          <tr><td style={{border: 0}}><NavLink to={"/"}> Back To All Runs</NavLink></td></tr>
        </tbody></table>

        <table className="big"><tbody>
          <tr>
            <th>Build
            <select onChange={filterByAll} id="build_fltr" name="filters">
              <option value=" "> </option>
              <option value="dev">Dev</option>
              <option value="rel">Release</option>
            </select>
            </th>
            <th>Features
            <input style={{width: "100%"}} type="text"  name="filters" id="features_fltr" onChange={filterByAll} />
            </th>
            <th>Test
            <input style={{width: "100%"}} type="text"  name="filters" id="name_fltr" onChange={filterByAll} />
            </th>
            <th>Status
            <input style={{width: "100%"}} type="text"  name="filters" id="status_fltr" onChange={filterByAll} />
            </th>
            <th>Logs
            </th>
            <th>Run Time <button style={{textDecoration: "none"}} onClick={orderByTestTime}>&#8597;</button></th>
            <th>Started</th>
            <th>Finished</th>
        </tr>
        {filteredRuns.map(a_test => {
            const timeStats = common.formatTimeStats(a_test);
            return (
              <tr key={a_test.test_id}>
                <td>
                  {a_test.is_release ? 'Release' : 'Dev'}
                </td>
                <td style={{fontSize: "x-small", "margin": 0}}>
                    {(a_test.features || '').replace('--features ', '').replace(/,/, ',​')}
                </td>
                <td>
                    <NavLink to={"/test/" + a_test.test_id} >{a_test.name}</NavLink>
                </td>
                <td style={{color: common.testStatusColour(a_test.status)}}>{a_test.status}<br/>
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
      </>
    );
}

export default ARun;
