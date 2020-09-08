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

    var filterClick = event  => {
      var filters = document.getElementsByName("filters");
      for (var item of filters) {
        item.value = "";
      }
      setFilteredRuns(aRun);
    }

    var filterHandler = event => {
      const fltr = event.target.value.toLowerCase();
      var id = event.target.id;
      setFilteredRuns(
        aRun.filter(
          item =>
            (item[id].toLowerCase().includes(fltr)) 
        )
      );
    };

    return (
      <div>
        <table style={{"border" : "0px", "width": "40%"}}> <tbody>
          <tr><td style={{"border": "0px"}}><NavLink to={"/"}> Back To All Runs</NavLink></td></tr>
        </tbody></table>
    
        <table  className="big"><tbody>
          <tr>
            <th>Type
            <input style={{"width":"100%"}} type="text"  name="filters" id="type" onChange={filterHandler} onClick={filterClick}/>
            </th>
            <th style={{"width": "40%"}}>Test
            <input style={{"width":"100%"}} type="text"  name="filters" id="name" onChange={filterHandler} onClick={filterClick}/>
            </th>
            <th>Status
            <input style={{"width":"100%"}} type="text"  name="filters" id="status" onChange={filterHandler} onClick={filterClick}/>
            </th>
            <th>Logs
            </th>
            <th>Test Time / Run Time</th>
            <th>Started</th>
            <th>Finished</th>
        </tr>
        {filteredRuns.map((a_run,i) =>
            <tr key={a_run.test_id}>
            <td>{a_run.type}</td>
            <td style={{"width": "30%"}}>
                <NavLink to={"/test/" + a_run.test_id} >{a_run.test}</NavLink>
            </td>
            <td style={{"color": StatusColor(a_run.status)}}>{a_run.status}<br/>
            {RenderHistory(a_run)}
            </td>
            <td>
                   {Object.entries(a_run.logs).map( ([type, value]) => 
                 <a style={{"color": value.stack_trace ? "red" : 
                                     "LONG DELAY" in String(value.patterns) ? "purple" : "blue"}} 
                  href={value.storage}> {type + "(" + value.full_size + ")" } 
                 
                 </a> 
              )}
            </td>
            <td>{a_run.test_time} / {a_run.run_time}</td>
                
            <td>{a_run.started}</td>
            <td>{a_run.finished}</td>
            </tr>  
        )}
        </tbody></table>
      </div>
    );
}
 
export default ARun;
