import React, { useState, useEffect } from "react";
import { NavLink, HashRouter } from "react-router-dom";

import * as common from "./common";


function AllRuns () {
    const [allRuns, setAllRuns] = useState([]);
    const [filteredRuns, setFilteredRuns] = useState([])

    useEffect(() => {
        common.fetchAPI('/runs').then(data => {
            setAllRuns(data);
            setFilteredRuns(data)
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
        common.fetchAPI('/run/' + (0 | id), true)
            .then(data => console.log(data));
    };

    const buildName = build => {
        const features = (build.features || '').replace(/--features[= ]/g, '');
        let tag = features;
        if (tag === 'nightly_protocol' ||
            tag === 'nightly_protocol,nightly_protocol_features') {
            tag = 'Nightly';
        } else if (tag === 'sandbox') {
            tag = 'Sandbox';
        } else if (tag.startsWith('nightly_protocol,protocol_feature_') &&
                   tag.indexOf(',', 34) === -1) {
            tag = tag.substr(34).split('_').map(
                word => word.substr(0, 1).toUpperCase() + word.substr(1))
        }
        const base = build.is_release ? 'Release' : 'Dev';
        return tag ? <b title={features}>{base}/{tag}</b> : <b>{base}</b>;
    }

    const testCounter = (build, name, word=undefined) => {
        const count = build.tests[name];
        return count
            ? <div className={'status status-' + name}>{count} {word || name}</div>
            : null;
    };

    const formatRow = a_run =>
      <tr key={a_run.id}>
        <td>{common.commitLink(a_run)}</td>
        <td><NavLink to={"/run/" + a_run.id} name="title">{a_run.title}</NavLink></td>
        <td>{a_run.requester}</td>
        <td>
          {a_run.builds.map(build =>
            <div key={build.build_id}>
              <NavLink to={"/build/" + build.build_id}
                       className="build_status"
                       style={{background: common.buildStatusColour(build.status)}}>
                {buildName(build)} {build.status}
              </NavLink>
              <div>
                { testCounter(build, 'passed') }
                { testCounter(build, 'failed') }
                { testCounter(build, 'timeout') }
                { testCounter(build, 'build_failed', 'build failed') }
                { testCounter(build, 'canceled', 'cancelled') }
                { testCounter(build, 'ignored') }
                { testCounter(build, 'pending') }
                { testCounter(build, 'running') }
              </div>
            </div>
          )}
        </td>
        <td><button style={{borderRadius: "0.25em"}} onClick={cancelRun(a_run.id)}>x</button></td>
      </tr>;

    return (
      <HashRouter>
        <table className="big App">
          <thead>
            <tr>
              <th>Branch
                  <input style={{width: "100%"}} type="text" name="filters" id="branch" onChange={filterHandler}/></th>
              <th>Title
                  <input style={{width: "100%"}} type="text" name="filters" id="title" onChange={filterHandler}/></th>
              <th>User
                  <input style={{width: "100%"}} type="text" name="filters" id="requester" onChange={filterHandler}/></th>
              <th>Status</th>
              <th>x</th>
            </tr>
          </thead>
          <tbody>{filteredRuns.map(formatRow)}</tbody>
        </table>
      </HashRouter>
    );
}

export default AllRuns;