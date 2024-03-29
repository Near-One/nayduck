import React, { useEffect } from "react";
import { NavLink } from "react-router-dom";
import * as ansicolor from "ansicolor";


export function useTitle(title) {
    useEffect(() => {
        if (!title) {
            return () => void 0;
        }
        const prev = document.title;
        document.title = title ? title + ' — NayDuck' : 'NayDuck';
        return () => void(document.title = prev);
    });
}


export function statusClassName(base, status) {
    return base + '-' + status.replace(/ /g, '_').toLowerCase();
}


export function renderHistory(a_test, branch=null) {
    const statuses = ['PASSED', 'OTHER', 'FAILED'];
    const keyPrefix = '' + a_test.test_id + '/' + (branch || '') + '/';
    const history = <ul>{a_test.history.map((count, index) => {
        const status = statuses[index];
        return status && <li key={keyPrefix + index} className={
            statusClassName('text', status)
        }>{branch ? status : status.substr(0, 1)}:{count}</li>;
    })}</ul>;
    const inner = branch
          ? <>History on <b>{branch}</b>: {history}</>
          : <small>{history}</small>;
    return a_test.test_id
        ? <NavLink to={"/test_history/" + (0 | a_test.test_id)}
                   className="history">{inner}</NavLink>
        : inner;
}


export function fetchAPI(path, post=false) {
    const url = '/api' + path;
    const opts = {
        headers: { 'Accept': 'application/json' },
        method: post ? 'POST' : 'GET',
    };
    return fetch(url, opts)
        .then(response => response.json())
        .catch(err => console.log('Fetch Error :-S', err));
}


export function branchLink(object) {
    if (!object.sha) {
        return null;
    }
    const branch = object.branch;
    const sha = object.sha.substr(0, 7);
    const href = 'https://github.com/near/nearcore/commit/' + sha;
    const link = <a href={href}>{sha}</a>;
    return branch ? <>{branch} <small>({link})</small></> : link;
}


function parseCommitSubject(title) {
    const m = /\s*\(#([0-9]{4,})\)\s*$/.exec(title || '');
    if (!m) {
        return [title, null];
    }
    const href = 'https://github.com/near/nearcore/pull/' + m[1];
    return [
        title.substr(0, m.index).trim(),
        <small>(<a href={href}>#{m[1]}</a>)</small>
    ];
}


export function commitNavLink(to, subject) {
    const [title, prLink] = parseCommitSubject(subject || '');
    const link = <NavLink to={to}>{title}</NavLink>;
    return prLink ? <>{link} {prLink}</> : link;
}


export function commitRow(object) {
    const branch = branchLink(object);
    let [title, prLink] = parseCommitSubject(object.title || '');
    if (prLink) {
        title = <>{title} {prLink}</>;
    }
    return <tr><td>Commit</td><td>{branch} {title}</td></tr>;
}


export function formatRequester(requester, makeDiv) {
    if (!requester) {
        return null;
    } else if (requester !== 'NayDuck') {
        return makeDiv ? <div>{requester}</div> : requester;
    } else if (makeDiv) {
        return <div className="nightly">NayDuck</div>;
    } else {
        return <span className="nightly">NayDuck</span>;
    }
}


function formatSize(size) {
    if (size < 1000) {
        return '' + size;
    }
    for (const suffix of 'kMGTPEZ') {
        if (size < 10000) {
            return '' + (Math.round(size / 100) / 10) + ' ' + suffix;
        }
        size /= 1000;
        if (size < 1000) {
            return '' + Math.round(size) + ' ' + suffix;
        }
    }
    return '' + Math.round(size) + ' Y';
}


function logLink(log, test_id=null) {
    const className = log.stack_trace ? 'log-failed' : 'log-normal';
    const size = <small>({formatSize(log.size)})</small>;
    const link = <>{
        log.storage ? <a className={className} href={log.storage}>{log.type}</a>
                    : <span className={className}>{log.type}</span>
    } {size}</>;
    const key = test_id ? ('log/' + test_id + '/' + log.type) : null;
    return key ? <React.Fragment key={key}>• {link} </React.Fragment> : link;
}


export function allLogLinks(logs, test_id) {
    return logs ? logs.map(log => logLink(log, test_id)) : null;
}


function logBlob(log) {
    if (!log.log) {
        return <small className="blob">{
            log.size ? '(binary file)' : '(empty)'
        }</small>;
    }

    const makeSpan = (span, idx) => {
        if (!span.css) {
            return span.text;
        }
        const style = {};
        for (const prop of span.css.replace(/;$/, '').split(';')) {
            const [key, value] = prop.split(':', 2);
            style[key.replace(/-([a-z])/g, (_, m) => m.toUpperCase())] = value;
        }
        return <span style={style} key={idx}>{span.text}</span>;
    };

    const formatBlob = blob => {
        blob = blob
            .replace(/^(?:\s*\n)+/, '')
            .replace(/(?:\n\s*)+$/, '\n');
        const spans = ansicolor.parse(blob).spans.filter(span => span.text);
        return <>{spans.map(makeSpan)}</>;
    };

    const parts = log.log.split('\n...\n');
    return parts.length === 2 ? <div className="blob">{
        formatBlob(parts[0])
    }<div className="ellipsis">⋮</div>{
        formatBlob(parts[1])
    }</div> : <div className="blob">{
        formatBlob(log.log)
    }</div>;
}


export function logRow(log) {
    const key = log.type;
    return <tr key={key}><td>{logLink(log)}</td><td>{logBlob(log)}</td></tr>;
}


function pad(value) {
    return (value < 10 ? '0' : '') + value;
}


function formatTZOffset(value) {
    if (!value) {
        return 'UTC';
    }
    const ret = value < 0 ? 'UTC+' : 'UTC-';
    if (value < 0) {
        value = -value;
    }
    const m = value % 60;
    return ret + pad(0 | (value / 60)) + (m ? ':' + pad(m) : '');
}


export function formatDateTime(timestampMs, utc=false) {
    if (!timestampMs) {
        return null;
    }
    const date = new Date(timestampMs);
    const year = utc ? date.getUTCFullYear() : date.getFullYear();
    const month = pad((utc ? date.getUTCMonth() : date.getMonth()) + 1);
    const day = pad(utc ? date.getUTCDate() : date.getDate());
    const hours = pad(utc ? date.getUTCHours() : date.getHours());
    const minutes = pad(utc ? date.getUTCMinutes() : date.getMinutes());
    const seconds = pad(utc ? date.getUTCSeconds() : date.getSeconds());
    const offset = utc ? '' : (' ' + formatTZOffset(date.getTimezoneOffset()));
    return `${year}-${month}-${day} ${hours}:${minutes}:${seconds}${offset}`;
}


function formatTimeDelta(milliseconds) {
    milliseconds = 0 | milliseconds;
    const sign = milliseconds < 0 ? '-' : '';
    if (milliseconds < 0) {
        milliseconds = -milliseconds;
    }
    let h = 0 | (milliseconds / 1000);
    const s = h % 60;
    h = 0 | (h / 60);
    const m = h % 60;
    h = 0 | (h / 60);

    return `${sign}${pad(h)}:${pad(m)}:${pad(s)}`;
}


export function getTimeDelta(object, missingValue=null) {
    if (object.started) {
        const finished = object.finished || (0 | (new Date()).getTime());
        return finished - object.started;
    } else {
        return missingValue;
    }
}


export function formatTimeStats(object) {
    const started = formatDateTime(object.started);
    const finished = formatDateTime(object.finished);
    const delta = getTimeDelta(object);
    return {
        started,
        finished,
        delta: delta === null ? null : formatTimeDelta(delta)
    };
}


export function formatTimeStatsRows(runTimeCaption, object) {
    if (!object.started) {
        return null;
    }
    const stats = formatTimeStats(object);
    let runTime = stats.delta;
    if (!stats.finished) {
        runTime = <span className="run-time-pending">{runTime}</span>;
    }
    if (object.timeout) {
        const timeout = formatTimeDelta(object.timeout * 1000);
        runTime = <>{runTime} / {timeout}</>;
    }
    return <>
        <tr><td>{runTimeCaption}</td><td>{runTime}</td></tr>
        <tr><td>Started</td><td>{stats.started}</td></tr>
        {stats.finished && <tr><td>Finished</td><td>{stats.finished}</td></tr>}
    </>;
}


export function renderBreadCrumbs(ids={}, history=[]) {
    const { runId, buildId, testId } = ids;
    const allLink = <td><NavLink to="/">« all runs</NavLink></td>;
    const runLink = runId &&
        <td><NavLink to={'/run/' + (runId | 0)}>« run #{runId}</NavLink></td>;
    const buildLink = buildId &&
        <td><NavLink to={'/build/' + (buildId | 0)}>« build #{buildId}</NavLink></td>;
    const testLink = testId &&
        <td><NavLink to={'/testId/' + (testId | 0)}>« test #{testId}</NavLink></td>;
    const historyCells = history.map((entry, idx) => {
        const [hist, branch] = entry;
        return hist && <td key={idx}>{renderHistory(hist, branch, '' + idx)}</td>
    });
    return <table id="nav"><tbody><tr>
        {allLink}{runLink}{buildLink}{testLink}{historyCells}
    </tr></tbody></table>;
}
