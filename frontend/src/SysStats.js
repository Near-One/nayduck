import React from 'react';

import * as common from "./common"

class SysStats extends React.Component {
    constructor(props) {
        super(props);
        this.state = null;
        this.timer = 0;
    }

    componentDidMount() {
        this.timer = setInterval(() => this.tick(), 10000);
        this.tick();
    }

    componentWillUnmount() {
        clearInterval(this.timer);
        this.timer = 0;
    }

    tick() {
        common.fetchAPI('/sys-stats').then(data => this.setState(data));
    }

    render() {
        const sysStatsLine = (stats, verb) => {
            let line = (stats[verb] || 0) + ' ' + verb;
            if (stats.pending) {
                line += ' + ' + stats.pending + ' pending';
            }
            return line;
        };

        return this.state && <div id="sysstats"><div>
            {sysStatsLine(this.state.build, 'building')}<br/>
            {sysStatsLine(this.state.test, 'running')}
        </div></div>;
    }
}

export default SysStats;
