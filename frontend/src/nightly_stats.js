import React, { useState, useEffect } from "react";
import { NavLink } from "react-router-dom";

import * as common from "./common"


const ONE_MINUTE = 60 * 1000;
const ONE_HOUR = 60 * ONE_MINUTE;
const ONE_DAY = 24 * ONE_HOUR;
const ONE_WEEK = 7 * ONE_DAY;


function ordinal(num, noun) {
    return num + ' ' + noun + (num === 1 ? '' : 's');
}


function businessDaysDiff(startTime, endTime) {
    let diff = endTime - startTime;

    // 1970/01/01 was Thursday
    const getDoW = time => (4 + (0 | (time / ONE_DAY))) % 7;

    // If start date falls on a weekend forward it to start of Monday
    let dow = getDoW(startTime);
    if (dow === 0 || dow === 6) {
        diff -= (dow ? 2 : 1) * ONE_DAY;
        diff += startTime % ONE_DAY;
    }

    // If end date falls on a weekend move it backwards to end of Friday
    dow = getDoW(endTime);
    if (dow === 0 || dow === 6) {
        diff -= (dow ? 0 : 1) * ONE_DAY;
        diff -= endTime % ONE_DAY;
    }

    if (diff < ONE_MINUTE) {
        return null;
    } else if (diff < ONE_DAY) {
        return ordinal(Math.round(diff * 100 / ONE_HOUR) / 100, 'hour');
    }

    let parts;
    if (diff < ONE_WEEK) {
        const hours = 0 | (diff / ONE_HOUR);
        parts = [0 | (hours / 24), 'business day', hours % 24, 'hour'];
    } else {
        const days = 0 | (diff / ONE_DAY);
        parts = [0 | (days / 7), 'week', days % 7, 'business day'];
    }
    const result = ordinal(parts[0], parts[1]);
    return parts[2] ? result + ' and ' + ordinal(parts[2], parts[3]) : result;
}


function NightlyStats(props) {
    const [nightlyEvents, setNightlyEvents] = useState({});

    useEffect(() => {
        common.fetchAPI('/nightly-events').then(setNightlyEvents);
    }, []);

    const lastEvent = [new Date().getTime()];
    const renderTestEvents = test => {
        const name = test[0];
        const events = test[1];
        const renderRow = (event, index) => {
            const [timestamp, runId, status] = event;
            const nextTimestamp = (events[index + 1] || lastEvent)[0];
            const className = common.statusClassName('text', status)
            return <tr key={name + '/' + runId}>
              {index ? null : <td style={{verticalAlign: 'top'}}
                                  rowspan={events.length}>{name}</td>}
              <td><NavLink to={'/run/' + runId}>{
                  common.formatDateTime(timestamp, true).substr(0, 10)
              }</NavLink></td>
              <td className={className}>{status}</td>
              <td className={className}>{
                  businessDaysDiff(timestamp, nextTimestamp)
              }</td>
            </tr>;
        };
        return <tbody key={name}>{events.map(renderRow)}</tbody>;
    };

    const tests = Object.entries(nightlyEvents.tests || {});
    tests.sort((a, b) => a[0] < b[0] ? -1 : 1);
    common.useTitle('Nightly Stats');
    return tests.length ? <>
        {common.renderBreadCrumbs({runId: nightlyEvents.last_run_id})}
        <table className="big">
          <thead>
            <tr>
              <th>Name</th>
              <th>Date</th>
              <th>Status</th>
              <th>Time in state <small>(excluding weekends)</small></th>
            </tr>
          </thead>
          {tests.map(renderTestEvents)}
        </table>
      </> : null;
}

export default NightlyStats;
