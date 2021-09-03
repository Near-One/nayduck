import React, { useState, useEffect } from "react";
import { NavLink } from "react-router-dom";

import * as common from "./common";


function Build (props) {
    const [BuildInfo, setBuildInfo] = useState({});

    useEffect(() => {
        common.fetchAPI('/build/' + (0 | props.match.params.build_id))
            .then(data => setBuildInfo(data));
    }, [props.match.params.build_id]);

    const timeStats = common.formatTimeStats(BuildInfo);
    const statusCell = BuildInfo.status ? <td className={
        common.statusClassName('text', BuildInfo.status)
    }>{BuildInfo.status}</td> : <td></td>;

    const logRow = name => {
        const id = (0 | props.match.params.build_id);
        const blob = BuildInfo[name] || '';
        const log = {
            storage: '/logs/build/' + id + '/' + name,
            patterns: '',
            log: blob,
            size: blob.length,
            type: name
        };
        return <tr><td>{
            common.logLink(log)
        }</td><td>{
            common.logBlob(log)
        }</td></tr>;
    };

    return <>
      <table className="nav"><tbody>
        <tr><td><NavLink to="/">« Back to all runs</NavLink></td></tr>
      </tbody></table>
      <table className="big"><tbody>
        <tr>
            <td>Commit</td>
            <td>{common.commitLink(BuildInfo)} {BuildInfo.title}</td>
         </tr>
        <tr><td>Requested by</td><td>{BuildInfo.requester}</td></tr>
        <tr>
            <td>Build Type</td>
            <td>{BuildInfo.is_release ? 'Release' : 'Dev'}
                {BuildInfo.features}</td>;
        </tr>
        <tr><td>Build Time</td><td>{timeStats.delta}</td></tr>
        <tr><td>Finished</td><td>{timeStats.finished}</td></tr>
        <tr><td>Started</td><td>{timeStats.started}</td></tr>
        <tr><td>Status</td>{statusCell}</tr>
        <tr><th colSpan="2">Logs</th></tr>
        {logRow('stderr')}
        {logRow('stdout')}
      </tbody></table>
    </>;
}

export default Build;
