import React, { useState, useEffect, useContext } from "react";
import { NavLink } from "react-router-dom";

import * as App from "./App";
import * as common from "./common";


function AllRuns () {
    const [allRuns, setAllRuns] = useState([]);
    const [filteredRuns, setFilteredRuns] = useState([])
    const {isAuthorised} = useContext(App.AuthContext)[0];

    const loadAllRuns = () => {
        common.fetchAPI('/runs').then(data => {
            setAllRuns(data);
            setFilteredRuns(data)
        });
    };

    const cancelOrRetryRun = (id, action) => event => {
        common.fetchAPI('/run/' + (0 | id) + '/' + action, true).then(data => {
            console.log(data)
            if (data) {
                loadAllRuns();
            }
        });
    };

    useEffect(loadAllRuns, []);

    const filterHandler = event => {
      let fltr = document.getElementById('branch').value.toLowerCase();
      let filtered = (
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

    const cancelButton = a_run => {
        const canCancel = a_run.builds.some(
            build => build.status === 'PENDING' || build.tests['pending']);
        return canCancel
            ? <button onClick={cancelOrRetryRun(a_run.run_id, 'cancel')}>×</button>
            : null;
    };

    const retryButton = a_run => {
        const canRetry = a_run.builds.some(build => {
            if (build.status !== 'BUILD DONE' && build.status !== 'SKIPPED') {
                return false;
            }
            const {timeout, failed, build_failed} = build.tests;
            return !!(timeout || ((failed || 0) - (build_failed || 0)));
        });
        return canRetry
            ? <button onClick={cancelOrRetryRun(a_run.run_id, 'retry')}>↺</button>
            : null;
    };

    const formatRow = a_run => <tr key={a_run.run_id}>
      <td>{common.commitLink(a_run)}</td>
      <td><NavLink to={'/run/' + a_run.run_id}>{a_run.title}</NavLink></td>
      <td>{a_run.requester}<br/><small>{
        common.formatDateTime(a_run.timestamp)
      }</small></td>
      <td>{
        a_run.builds.map(build => <div key={build.build_id}>
          <NavLink to={"/build/" + build.build_id}
                   className={'status ' + common.statusClassName('build_status', build.status)}>
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
        </div>)
      }</td>
      {isAuthorised ? <td>
         {cancelButton(a_run)}
         {retryButton(a_run)}
       </td> : null}
    </tr>;

    return <table className="big list">
      <thead>
        <tr>
          <th>Branch <input id="branch" onChange={filterHandler}/></th>
          <th>Title <input id="title" onChange={filterHandler}/></th>
          <th>User <input id="requester" onChange={filterHandler}/></th>
          <th>Status</th>
          {isAuthorised ? <th></th> : null }
        </tr>
      </thead>
      <tbody>{filteredRuns.map(formatRow)}</tbody>
    </table>;
}

export default AllRuns;
