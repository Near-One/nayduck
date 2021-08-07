import React, { useState, useEffect  } from "react";
import { NavLink } from "react-router-dom";

import * as common from "./common";


function ARun (props) {
    const [orderDescTestTime, setOrderDescTestTime] = useState(true);
    const [aRun, setARun] = useState([]);
    const [filteredRuns, setFilteredRuns] = useState([])

    useEffect(() => {
        common.fetchAPI('/run/' + (0 | props.match.params.run_id))
            .then(data => {
                setARun(data);
                setFilteredRuns(data)
            });
    }, [props.match.params.run_id]);

    var filterByAll = event => {
      var fltr = document.getElementById('build_fltr').value.toLowerCase();
      var filtered = fltr === 'debug' || fltr === 'release'
          ? aRun.filter(item => (fltr === 'debug') === !item.is_release)
          : aRun;
      fltr = document.getElementById('features_fltr').value.toLowerCase();
      filtered = fltr
        ? filtered.filter(item => fltr === ' '
                          ? !item.build.features
                          : item.build.features.toLowerCase().includes(fltr))
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

    var orderByTestTime = event => {
      var filtered = [...aRun];
      if (orderDescTestTime) {
        filtered = filtered.sort((a, b) => a.run_time > b.run_time ? 1 : -1);
      } else {
        filtered = filtered.sort((a, b) => a.run_time < b.run_time ? 1 : -1);
      }
      setARun(filtered);
      filtered = [...filteredRuns]
      if (orderDescTestTime) {
        filtered = filtered.sort((a, b) => a.run_time > b.run_time ? 1 : -1);
      } else {
        filtered = filtered.sort((a, b) => a.run_time < b.run_time ? 1 : -1);
      }
      setFilteredRuns(filtered);
      setOrderDescTestTime(!orderDescTestTime);
    }

    return (
      <div>
        <table style={{"border" : "0px", "width": "40%"}}> <tbody>
          <tr><td style={{"border": "0px"}}><NavLink to={"/"}> Back To All Runs</NavLink></td></tr>
        </tbody></table>

        <table  className="big"><tbody>
          <tr>
            <th>Build
            <select class="dropdown" onChange={filterByAll} id="build_fltr" name="filters">
              <option value=" "> </option>
              <option value="debug">Debug</option>
              <option value="release">Release</option>
            </select>
            </th>
            <th>Features
            <input style={{"width":"100%"}} type="text"  name="filters" id="features_fltr" onChange={filterByAll} />
            </th>
            <th style={{"width": "40%"}}>Test
            <input style={{"width":"100%"}} type="text"  name="filters" id="name_fltr" onChange={filterByAll} />
            </th>
            <th>Status
            <input style={{"width":"100%"}} type="text"  name="filters" id="status_fltr" onChange={filterByAll} />
            </th>
            <th>Logs
            </th>
            <th>Run Time <button style={{"text-decoration":"none"}} onClick={orderByTestTime}>&#8597;</button></th>
            <th>Started</th>
            <th>Finished</th>
        </tr>
        {filteredRuns.map((a_run,i) =>
            <tr key={a_run.test_id}>
            <td style={{"font-size": "x-small", "margin":"0"}}>
              {a_run.build.is_release ? 'Release' : 'Debug'}
            </td>
            <td style={{"font-size": "x-small", "margin":"0"}}>
               {a_run.build.features}

            </td>
            <td style={{"width": "30%"}}>
                <NavLink to={"/test/" + a_run.test_id} >{a_run.name}</NavLink>
            </td>
            <td style={{"color": common.StatusColor(a_run.status)}}>{a_run.status}<br/>
            {common.RenderHistory(a_run)}
            </td>
            <td>{Object.entries(a_run.logs).map(([type, value]) => common.logLink(value, type, true))}</td>
            <td>{a_run.run_time} </td>
            <td>{a_run.started}</td>
            <td>{a_run.finished}</td>
            </tr>
        )}
        </tbody></table>
      </div>
    );
}

export default ARun;
