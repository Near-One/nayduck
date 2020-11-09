import React, { useState, useEffect, useContext } from "react";

import {
    NavLink,
    HashRouter,
  } from "react-router-dom";

import { ServerIp, GitRepo }  from "./common"
import { AuthContext } from "./App";



function AllRuns () {
    const { state } = useContext(AuthContext);

    const [allRuns, setAllRuns] = useState([]);
    
    const [member, setMember] = useState([]);
    
    const [filteredRuns, setFilteredRuns] = useState([])
    
    const { organizations_url } = state.user
    fetch(organizations_url, {  
    })
    .then(response => response.json())
    .then(data => {
     //for (var d of data) {

       // if (d["login"] === "nearprotocol") {
       //     console.log("Welcome to Nay!");
       //     setMember(true);
       // }
     //}
    });
  
    
    useEffect(() => {
            fetch(ServerIp(), {
              headers : { 
                'Content-Type': 'application/json',
                'Accept': 'application/json'
               }
              }).then((response) => response.json())
              .then(data => {
              setAllRuns(data);
              console.log(data);
              setFilteredRuns(data)
            })
            
            .catch(function(err) {
              console.log('Fetch Error :-S', err);
            });
    }, []);

    var filterHandler = event => {
      var fltr = document.getElementById('branch').value.toLowerCase();
      var filtered = (
        allRuns.filter(
          item =>
            (item['branch'].toLowerCase().includes(fltr) || item['sha'].toLowerCase().includes(fltr))
        )
      );
      fltr = document.getElementById('title').value.toLowerCase();
      filtered = (
        filtered.filter(
          item =>
            (item['title'].toLowerCase().includes(fltr)) 
        )
      );
      fltr = document.getElementById('requester').value.toLowerCase();
      filtered = (
        filtered.filter(
          item =>
            (item['requester'].toLowerCase().includes(fltr)) 
        )
      );

      setFilteredRuns(filtered);
    };

    var cancelRun = id => event => {
      fetch(ServerIp() + '/cancel_the_run', {
        headers : { 
          'Content-Type': 'application/json',
          'Accept': 'application/json'
         },
         method: 'POST',
         body: JSON.stringify({'run_id': id}),
        }).then((response) => response.json())
        .then(data => {
          console.log(data);
      })
    }

    return (
        <div className="App">
        <HashRouter>
          <table className="big"><tbody>
          <tr>
            <th>Branch
            <input style={{"width":"100%"}} type="text" name="filters" id="branch" onChange={filterHandler}/>
            </th>
            <th style={{"width": "30%"}}>Title
            <input style={{"width":"100%"}} type="text" name="filters" id="title" onChange={filterHandler}/>
            </th>
            <th>User
            <input style={{"width":"100%"}} type="text" name="filters" id="requester" onChange={filterHandler}/>
            </th>
            <th width="40%">Status</th>
            { member > 0 ? <th>x</th>:''}
              
          </tr>
          {filteredRuns.map((a_run,i) =>
            <tr key={a_run.id}>
              <td><p style={{"font-size": "x-small", "margin":"0"}}>{a_run.branch}</p>
                <a href={GitRepo()+"/commit/"+a_run.sha.slice(0,7)}>
                    {a_run.sha.slice(0,7)}
                </a>
              </td>
              <td>
                <NavLink to={"/run/" + a_run.id} name="title">{a_run.title}</NavLink>
              </td>
              <td style={{"font-size": "x-small"}}>{a_run.requester}</td>
              
              <td >
                {a_run.builds.map((build,j) => 
                <div class="one_build">
                    <div class="build_status" style={{"background": build.status == "PENDING" ? "FF99FF" : 
                                                            build.status == "BUILDING" ? "#9999FF":
                                                            build.status == "BUILD DONE" ? "#CCFFCC":
                                                            build.status == "BUILD FAILED" ? "#FFCCCC": 
                                                            build.status == "SKIPPED" ? "#f0a3aa": "E0E0E0"}}>
                      <NavLink className="build_link" to={"/build/" + build.build_id} >
                      <b>{build.is_release == 0 ? 'Debug' : 'Release'}  
                        {build.features == "" ? " ": "/"}
                        {build.features == "--features nightly_protocol --features nightly_protocol_features" 
                          ? 'Nightly ' : build.features + " "}
                      </b>
                      {build.status} 
                      </NavLink>
                    </div>
                    <div>
                    { build.tests.passed > 0 ? <div class="status" style={{"background": "green", }}>{build.tests.passed} passed</div> : ''}
                    { build.tests.failed > 0 ? <div class="status" style={{"background": "red" , }}>{build.tests.failed} failed </div> : ''}
                    { build.tests.timeout > 0 ? <div class="status" style={{"background": "#f0a3aa", }}>{build.tests.timeout} timeout </div> : ''}
                    { build.tests.build_failed > 0 ? <div class="status" style={{"background": "#864E4E", }}>{build.tests.build_failed} build failed </div> : ''}
                    { build.tests.canceled > 0 ? <div class="status" style={{"background": "#FCF88C",}}> {build.tests.canceled} canceled </div> : ''}
                    { build.tests.ignored > 0 ? <div class="status" style={{"background": "grey", }}>{build.tests.ignored} ignored</div> : ''}
                    { build.tests.pending > 0 ? <div class="status" style={{"background": "#ED8CFC"}}> {build.tests.pending} pending </div> : ''}
                    { build.tests.running > 0 ? <div class="status" style={{"background": "#697DCB", }}>{build.tests.running} running</div> : ''}
                    </div>
                </div>
                )}
              </td> 
              { member > 0 ? <td><button style={{"border-radius": "4px", "cursor": "pointer"}}onClick={cancelRun(a_run.id)}>x</button></td> : ''}
            </tr>)
          }
          </tbody></table>
        </HashRouter>
        </div>
        );
}
  
export default AllRuns;
