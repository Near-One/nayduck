import React, { useState, useEffect } from "react";

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

    const logRow = (name, blob) => {
        const id = (0 | props.match.params.build_id);
        return blob ? common.logRow({
            storage: '/logs/build/' + id + '/' + name,
            log: blob,
            size: blob.length,
            type: name
        }) : null;
    };

    const logRows = () => {
        const stderr = BuildInfo.stderr;
        const stdout = BuildInfo.stdout;
        return stderr || stdout ? <>
            <tr><th colSpan="2">Logs</th></tr>
            {logRow('stderr', stderr)}
            {logRow('stdout', stdout)}
        </> : null;
    };

    const buildType = (() => {
        const type = BuildInfo.is_release ? 'Release' : 'Dev';
        const features = BuildInfo.features;
        if (!features) {
            return type;
        }
        return type + ' --features=' + features;
    })();

    common.useTitle((BuildInfo.is_release ? 'Release' : 'Dev') + ' build #' +
                    props.match.params.build_id);
    return <>
      {common.renderBreadCrumbs({runId: BuildInfo.run_id})}

      <table className="big"><tbody>
        {common.commitRow(BuildInfo)}
        <tr><td>Requested by</td><td>{BuildInfo.requester}</td></tr>
        <tr><td>Build Type</td><td>{buildType}</td></tr>
        <tr><td>Build Time</td><td>{timeStats.delta}</td></tr>
        <tr><td>Finished</td><td>{timeStats.finished}</td></tr>
        <tr><td>Started</td><td>{timeStats.started}</td></tr>
        <tr><td>Status</td>{statusCell}</tr>
        {logRows()}
      </tbody></table>
    </>;
}

export default Build;
