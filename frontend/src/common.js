import React from "react";
import {
    NavLink,
  } from "react-router-dom";
import GithubIcon from "mdi-react/GithubIcon";
import * as ansicolor from "ansicolor";


export function statusClassName(base, status) {
    return base + '-' + status.replace(/ /g, '_').toLowerCase();
}


export function renderHistory(a_test, branch = null) {
    const statuses = ['PASSED', 'OTHER', 'FAILED'];
    const history = <ul>{a_test.history.map((count, index) => {
        const status = statuses[index];
        return status
            ? <li key={branch + '/history/' + index} className={
                      statusClassName('text', status)
              }>{branch ? status : status.substr(0, 1)}:{count}</li>
            : null;
    })}</ul>;
    const inner = branch
          ? <>This test history for branch <b>{branch}</b>: {history}</>
          : <small>{history}</small>;
    return <NavLink to={"/test_history/" + a_test.test_id}
                    className="history">{inner}</NavLink>
}


export function renderHistoryCell(history, branch) {
    return history
        ? <td>{renderHistory(history, branch)}</td>
        :  null;
}


function apiBaseHref() {
    return process.env.REACT_APP_SERVER_IP;
}


export function fetchAPI(path, post=false) {
    const url = apiBaseHref() + '/api' + path;
    const opts = {
        headers: { 'Accept': 'application/json' },
        method: post ? 'POST' : 'GET',
    };
    return fetch(url, opts)
        .then(response => response.json())
        .catch(err => console.log('Fetch Error :-S', err));
}


export function commitLink(object) {
    if (!object.branch || !object.sha) {
        return null;
    }
    const branch = object.branch;
    const sha = object.sha.substr(0, 7);
    const url = process.env.REACT_APP_GIT_REPO + '/commit/' + sha;
    return (<>{branch} <small>(<a href={url}>{sha}</a>)</small></>);
}


export function LoginPage(client_id, redirect_uri, data, setData) {
    console.log(redirect_uri);
    return (
    <section className="section-login">
        <div className="div-login">
          <img style={{width: "100%"}} alt="" src="duck.jpg"/>
          <span>{data.errorMessage}</span>
          <div className="github-login">
             {data.isLoading ? (
              <div className="loader-container">
                <div className="loader"></div>
              </div>
            ) : (
                <a
                  className="login-link"
                  href={`https://github.com/login/oauth/authorize?scope=read:org&client_id=${client_id}&redirect_uri=${redirect_uri}`}
                  onClick={() => {
                    setData({ ...data, errorMessage: "" });
                  }}
                >
                  <GithubIcon />
                  <span>Login with GitHub</span>
                </a>
            )}
          </div>
        </div>
      </section>
  );
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


export function logLink(log, test_id=null) {
    const className = !log.stack_trace
          ? String(log.patterns).includes("LONG DELAY") ? 'log-delayed'
                                                        : 'log-normal'
          : 'log-failed';
    const size = <small>({formatSize(log.size)})</small>;
    let href = log.storage;
    if (href.startsWith('/')) {
        href = apiBaseHref() + href;
    }
    const link = <>{
        href ? <a className={className} href={href}>{log.type}</a>
             : <span className={className}>{log.type}</span>
    } {size}</>;
    const key = test_id ? ('log/' + test_id + '/' + log.type) : null;
    return key ? <React.Fragment key={key}>• {link} </React.Fragment> : link;
}


export function allLogLinks(logs, test_id) {
    return logs ? logs.map(log => logLink(log, test_id)) : null;
}


function makeSpan(span, idx) {
    const style = {};
    for (const prop of span.css.split(';').filter(prop => prop)) {
        const [name, val] = prop.split(':', 2);
        style[name.replace(/-([a-z])/g, String.prototype.toUpperCase())] = val;
    }
    return <span style={style} key={idx}>{span.text}</span>;
}


export function logBlob(log) {
    return log.log ? <div className="blob">{
        ansicolor.parse(log.log).spans.filter(span => span.text).map(makeSpan)
    }</div> : <small className="blob">{
        log.size ? '(binary file)' : '(empty)'
    }</small>;
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


function formatDateTime(timestampMs) {
    if (!timestampMs) {
        return null;
    }
    const date = new Date(timestampMs);
    const year = date.getFullYear();
    const month = pad(date.getMonth() + 1);
    const day = pad(date.getDate());
    const hours = pad(date.getHours());
    const minutes = pad(date.getMinutes());
    const seconds = pad(date.getSeconds());
    const offset = formatTZOffset(date.getTimezoneOffset());
    return `${year}-${month}-${day} ${hours}:${minutes}:${seconds} ${offset}`;
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
