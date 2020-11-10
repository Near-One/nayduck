import React , { useState, useEffect  } from "react";
import {
    NavLink,
  } from "react-router-dom";

import { StatusColor, RenderHistory, ServerIp }  from "./common"


function ARun (props) {
    const [aRun, setARun] = useState([]);
    const [filteredRuns, setFilteredRuns] = useState([])

  
    useEffect(() => {

        fetch(ServerIp() + '/run', {
          headers : { 
            'Content-Type': 'application/json',
            'Accept': 'application/json'
           },
           method: 'POST',
           body: JSON.stringify({'run_id': props.match.params.run_id}),
          }).then((response) => response.json())
          .then(data => {
          setARun(data);
          setFilteredRuns(data)
          console.log(data);
          
        });
    }, []);

    var filterByAll = event => {
      var fltr = document.getElementById('build_fltr').value.toLowerCase();
      var filtered = (
        aRun.filter(
          item => (fltr == 'debug' ? item.is_release == 0 : 
                   fltr == 'release' ? item.is_release == 1 : item.is_release > -1 ) 
        )
      );
      fltr = document.getElementById('features_fltr').value.toLowerCase();
      console.log(filtered);
      filtered = (
        filtered.filter(
          item => (item['build']['features'] ? item['build']['features'].toLowerCase().includes(fltr): "".includes(fltr))
        )
      );
      fltr = document.getElementById('name_fltr').value.toLowerCase();
      filtered = (
        filtered.filter(
          item => (item['name'].toLowerCase().includes(fltr))
        )
      );
      fltr = document.getElementById('status_fltr').value.toLowerCase();
      filtered = (
        filtered.filter(
          item => (item['status'].toLowerCase().includes(fltr))
        )
      );
      setFilteredRuns(filtered);

    };

    var orderByTestTime = event => {
      console.log("sort")
      var filtered = aRun.sort((a, b) => a.test_time > b.test_time ? 1 : -1);
      console.log(filtered)
      setARun(filtered);
      filtered = filteredRuns.sort((a, b) => a.test_time > b.test_time ? 1 : -1);
      setFilteredRuns(filtered);
      
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
            <th>Test Time <button onClick={orderByTestTime}>v</button></th>
            <th>Started</th>
            <th>Finished</th>
        </tr>
        {filteredRuns.map((a_run,i) =>
            <tr key={a_run.test_id}>
            <td style={{"font-size": "x-small", "margin":"0"}}>
              {a_run.build.is_release == 0 ? 'Debug' : 'Release'}  
            </td>
            <td style={{"font-size": "x-small", "margin":"0"}}>
               {a_run.build.features}
            
            </td>
            <td style={{"width": "30%"}}>
                <NavLink to={"/test/" + a_run.test_id} >{a_run.name}</NavLink>
            </td>
            <td style={{"color": StatusColor(a_run.status)}}>{a_run.status}<br/>
            {RenderHistory(a_run)}
            </td>
            <td>
                   {Object.entries(a_run.logs).map( ([type, value]) => 
                 <a style={{"color": value.stack_trace ? "red" : 
                                    String(value.patterns).includes("LONG DELAY") ? "orange" : "blue"}} 
                  href={value.storage}> {type + "(" + value.full_size + ")" } 
                 
                 </a> 
              )}
            </td>
            <td>{a_run.test_time} </td>
            <td>{a_run.started}</td>
            <td>{a_run.finished}</td>
            </tr>  
        )}
        </tbody></table>
      </div>
    );
}
 
export default ARun;
