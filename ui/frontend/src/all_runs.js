import React, { useState, useEffect  } from "react";

import {
    NavLink,
    HashRouter,
  } from "react-router-dom";

import { ServerIp, GitRepo }  from "./common"


function AllRuns () {
    const [allRuns, setAllRuns] = useState([]);
    
    const [filteredRuns, setFilteredRuns] = useState([])

    useEffect(() => {
            fetch(ServerIp(), {
              headers : { 
                'Content-Type': 'application/json',
                'Accept': 'application/json'
               }
              }).then((response) => response.json())
              .then(data => {
              setAllRuns(data);
              setFilteredRuns(data)
              console.log(data);
            })
            
            .catch(function(err) {
              console.log('Fetch Error :-S', err);
            });
    }, []);

    var filterClick = event  => {
      var filters = document.getElementsByName("filters");
      for (var item of filters) {
        item.value = "";
      }
      setFilteredRuns(allRuns);
    }

    var filterHandler = event => {
      const fltr = event.target.value.toLowerCase();
      var id = event.target.id;
      setFilteredRuns(
        allRuns.filter(
          item =>
            (item[id].toLowerCase().includes(fltr)) 
        )
      );
    };

    return (
        <div className="App">
        <HashRouter>
          <table className="big"><tbody>
          <tr>
            <th>Branch
            <input style={{"width":"100%"}} type="text" name="filters" id="branch" onChange={filterHandler} onClick={filterClick}/>
            </th>
            <th style={{"width": "30%"}}>Title
            <input style={{"width":"100%"}} type="text" name="filters" id="title" onChange={filterHandler} onClick={filterClick}/>
            </th>
            <th>User
            <input style={{"width":"100%"}} type="text" name="filters" id="user" onChange={filterHandler} onClick={filterClick}/>
            </th>
            <th>Passed</th>
            <th>Failed</th>
              <th>Build fail</th>
              <th>Canceled</th>
              <th>Ignored</th>
              <th>Pending</th>
              <th>Running</th>
              <th>Timeout</th>
          </tr>
          {filteredRuns.map((a_run,i) =>
            <tr key={a_run.id}>
              <td>{a_run.branch}<br/>
                <a href={GitRepo()+"/commit/"+a_run.sha.slice(0,7)}>
                    {a_run.sha.slice(0,7)}
                </a>
              </td>
              <td>
                <NavLink to={"/run/" + a_run.id} name="title">{a_run.title}</NavLink>
              </td>
              <td>{a_run.user}</td>
              <td style={{"color": "green"}}>{a_run.passed}</td>
              <td style={{"color": "red"}}>{a_run.failed}</td>
              <td style={{"color": "#700610"}}>{a_run.build_failed}</td>
              <td>{a_run.canceled}</td>
              <td style={{"color": "grey"}}>{a_run.ignored}</td>
              <td>{a_run.pending}</td>
              <td style={{"color": "blue"}}>{a_run.running}</td>
              <td style={{"color": "#f0a3aa"}}>{a_run.timeout}</td>
            </tr>)
          }
          </tbody></table>
        </HashRouter>
        </div>
        );
}
  
export default AllRuns;
