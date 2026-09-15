const $ = (selector) => document.querySelector(selector);

const percent = (value) => `${Number(value).toFixed(2)}%`;
const dayFormat = new Intl.DateTimeFormat('zh-CN', { year: 'numeric', month: 'long', day: 'numeric' });

function parseDate(value) {
  return new Date(`${value}T12:00:00Z`);
}

function meetingAnnouncementTime(meeting) {
  const month = Number(meeting.end_date.slice(5, 7));
  const utcHour = month >= 3 && month <= 11 ? 18 : 19;
  return new Date(`${meeting.end_date}T${String(utcHour).padStart(2, '0')}:00:00Z`);
}

function decisionLabel(change) {
  if (!change) return '—';
  const bps = Number(change.delta_bps);
  if (change.decision === 'hike') return `加息 ${Math.abs(bps)} bp`;
  if (change.decision === 'cut') return `降息 ${Math.abs(bps)} bp`;
  return '调整区间';
}

function renderMetrics(rates, meetings) {
  const current = rates.current;
  $('#target-range').textContent = `${percent(current.lower)}–${percent(current.upper)}`;
  $('#target-asof').textContent = `有效日期 ${dayFormat.format(parseDate(current.as_of))}`;
  $('#latest-action').textContent = decisionLabel(rates.latest_change);
  $('#latest-action-date').textContent = rates.latest_change
    ? dayFormat.format(parseDate(rates.latest_change.effective_date))
    : '—';
  $('#effr').textContent = percent(rates.effective_rate.value);
  $('#effr-asof').textContent = `截至 ${dayFormat.format(parseDate(rates.effective_rate.as_of))}`;

  const now = new Date();
  const next = meetings.meetings.find((item) => meetingAnnouncementTime(item) > now);
  if (!next) {
    $('#next-meeting').textContent = '待官方公布';
    $('#countdown').textContent = '当前日历内没有未来会议';
    return;
  }
  $('#next-meeting').textContent = `${next.start_date.slice(5).replace('-', '/')}–${next.end_date.slice(8)}`;
  const updateCountdown = () => {
    const milliseconds = meetingAnnouncementTime(next) - new Date();
    if (milliseconds <= 0) {
      $('#countdown').textContent = '等待官方声明';
      return;
    }
    const totalHours = Math.floor(milliseconds / 3600000);
    const days = Math.floor(totalHours / 24);
    const hours = totalHours % 24;
    $('#countdown').textContent = `距预计声明约 ${days} 天 ${hours} 小时 · 纽约 14:00`;
  };
  updateCountdown();
  setInterval(updateCountdown, 60000);
}

function periodLabel(value) {
  const [year, month] = value.split('-');
  return `${year}年${Number(month)}月`;
}

function signed(value, digits = 1) {
  const number = Number(value);
  return `${number > 0 ? '+' : ''}${number.toFixed(digits)}`;
}

function payrollText(value) {
  return `${Number(value) >= 0 ? '+' : '-'}${(Math.abs(Number(value)) / 10).toFixed(1)}万`;
}

function renderMacroMetrics(macro) {
  const employment = macro.employment;
  const inflation = macro.inflation;
  $('#unemployment-rate').textContent = `${employment.unemployment_rate.toFixed(1)}%`;
  $('#unemployment-detail').textContent = `${periodLabel(employment.period)} · 较前月 ${signed(employment.unemployment_change_pp)} 个百分点`;
  $('#payroll-change').textContent = payrollText(employment.payroll_change_thousands);
  $('#payroll-detail').textContent = `${periodLabel(employment.period)} · 近3月均值 ${payrollText(employment.payroll_3m_average_thousands)}`;

  const indicators = [
    ['cpi', '#cpi-yoy', '#cpi-detail'],
    ['core_cpi', '#core-cpi-yoy', '#core-cpi-detail'],
    ['pce', '#pce-yoy', '#pce-detail'],
    ['core_pce', '#core-pce-yoy', '#core-pce-detail'],
  ];
  for (const [key, valueSelector, detailSelector] of indicators) {
    const item = inflation[key];
    $(valueSelector).textContent = `${item.yoy.toFixed(1)}%`;
    $(detailSelector).textContent = `${periodLabel(item.period)} · 环比 ${signed(item.mom)}%`;
  }
}

function chartYearLabels(rows, x, height) {
  const labels = [];
  const renderedYears = new Set();
  rows.forEach((row, index) => {
    const year = row.period.slice(0, 4);
    if ((index === 0 || row.period.endsWith('-01') || index === rows.length - 1) && !renderedYears.has(year)) {
      labels.push(`<text class="axis-label" x="${x(index).toFixed(1)}" y="${height - 7}" text-anchor="middle">${year}</text>`);
      renderedYears.add(year);
    }
  });
  return labels.join('');
}

function renderEmploymentChart(rows) {
  const host = $('#employment-chart');
  if (!rows.length) return;
  const width = 540;
  const height = 245;
  const margin = { top: 12, right: 36, bottom: 28, left: 42 };
  const plotWidth = width - margin.left - margin.right;
  const plotHeight = height - margin.top - margin.bottom;
  const x = (index) => margin.left + (index / Math.max(rows.length - 1, 1)) * plotWidth;
  const payrolls = rows.map((row) => Number(row.payroll_change_thousands));
  const payrollMax = Math.max(100, Math.ceil(Math.max(0, ...payrolls) / 100) * 100);
  const payrollMin = Math.min(0, Math.floor(Math.min(0, ...payrolls) / 100) * 100);
  const payrollRange = payrollMax - payrollMin || 1;
  const payrollY = (value) => margin.top + ((payrollMax - value) / payrollRange) * plotHeight;
  const unemployment = rows.map((row) => Number(row.unemployment));
  const unemploymentMin = Math.max(0, Math.floor((Math.min(...unemployment) - .5) * 2) / 2);
  const unemploymentMax = Math.ceil((Math.max(...unemployment) + .5) * 2) / 2;
  const unemploymentY = (value) => margin.top + ((unemploymentMax - value) / (unemploymentMax - unemploymentMin || 1)) * plotHeight;
  const barWidth = Math.max(2, (plotWidth / rows.length) * .62);
  const zeroY = payrollY(0);
  const bars = rows.map((row, index) => {
    const valueY = payrollY(Number(row.payroll_change_thousands));
    const y = Math.min(valueY, zeroY);
    const barHeight = Math.max(1, Math.abs(zeroY - valueY));
    const className = Number(row.payroll_change_thousands) < 0 ? 'payroll-bar negative' : 'payroll-bar';
    return `<rect class="${className}" x="${(x(index) - barWidth / 2).toFixed(1)}" y="${y.toFixed(1)}" width="${barWidth.toFixed(1)}" height="${barHeight.toFixed(1)}"/>`;
  }).join('');
  const line = rows.map((row, index) => `${index ? 'L' : 'M'} ${x(index).toFixed(1)} ${unemploymentY(Number(row.unemployment)).toFixed(1)}`).join(' ');
  host.innerHTML = `<svg viewBox="0 0 ${width} ${height}" aria-hidden="true">
    <line class="zero-line" x1="${margin.left}" y1="${zeroY.toFixed(1)}" x2="${width - margin.right}" y2="${zeroY.toFixed(1)}"/>
    ${bars}<path class="unemployment-line" d="${line}"/>
    <text class="axis-label" x="4" y="${margin.top + 5}">千人</text>
    <text class="axis-label" x="${width - 3}" y="${margin.top + 5}" text-anchor="end">失业率 ${unemploymentMax.toFixed(1)}%</text>
    ${chartYearLabels(rows, x, height)}
  </svg>`;
}

function renderInflationChart(rows) {
  const host = $('#inflation-chart');
  if (!rows.length) return;
  const width = 540;
  const height = 245;
  const margin = { top: 12, right: 18, bottom: 28, left: 35 };
  const plotWidth = width - margin.left - margin.right;
  const plotHeight = height - margin.top - margin.bottom;
  const x = (index) => margin.left + (index / Math.max(rows.length - 1, 1)) * plotWidth;
  const keys = ['cpi', 'core_cpi', 'pce', 'core_pce'];
  const values = rows.flatMap((row) => keys.map((key) => Number(row[key])).filter(Number.isFinite));
  const minValue = Math.min(0, Math.floor(Math.min(...values)));
  const maxValue = Math.max(1, Math.ceil(Math.max(...values)));
  const y = (value) => margin.top + ((maxValue - value) / (maxValue - minValue || 1)) * plotHeight;
  const grid = [];
  for (let value = minValue; value <= maxValue; value += 2) {
    const position = y(value).toFixed(1);
    grid.push(`<line class="grid" x1="${margin.left}" y1="${position}" x2="${width - margin.right}" y2="${position}"/>`);
    grid.push(`<text class="axis-label" x="${margin.left - 7}" y="${Number(position) + 4}" text-anchor="end">${value}%</text>`);
  }
  const paths = keys.map((key) => {
    let previousIndex = -2;
    const path = rows.map((row, index) => {
      const value = Number(row[key]);
      if (!Number.isFinite(value)) return '';
      const command = previousIndex === index - 1 ? 'L' : 'M';
      previousIndex = index;
      return `${command} ${x(index).toFixed(1)} ${y(value).toFixed(1)}`;
    }).join(' ');
    return `<path class="${key.replace('_', '-')}-line" d="${path}"/>`;
  }).join('');
  host.innerHTML = `<svg viewBox="0 0 ${width} ${height}" aria-hidden="true">${grid.join('')}${paths}${chartYearLabels(rows, x, height)}</svg>`;
}

function renderChart(history) {
  const host = $('#rate-chart');
  const width = 1060;
  const height = 360;
  const margin = { top: 20, right: 22, bottom: 40, left: 48 };
  const values = history.map((item) => Number(item.midpoint));
  const dates = history.map((item) => parseDate(item.effective_date).getTime());
  const minDate = Math.min(...dates);
  const maxDate = Math.max(...dates);
  const maxValue = Math.ceil(Math.max(...values) + 0.5);
  const x = (date) => margin.left + ((date - minDate) / (maxDate - minDate || 1)) * (width - margin.left - margin.right);
  const y = (value) => height - margin.bottom - (value / maxValue) * (height - margin.top - margin.bottom);

  let path = `M ${x(dates[0]).toFixed(1)} ${y(values[0]).toFixed(1)}`;
  for (let index = 1; index < history.length; index += 1) {
    path += ` H ${x(dates[index]).toFixed(1)} V ${y(values[index]).toFixed(1)}`;
  }
  const finalX = x(dates[dates.length - 1]).toFixed(1);
  const area = `${path} L ${finalX} ${height - margin.bottom} L ${x(dates[0]).toFixed(1)} ${height - margin.bottom} Z`;

  const rangeHistory = history.filter((item) => item.regime === 'target_range');
  let rangeBand = '';
  if (rangeHistory.length) {
    const rangeDates = rangeHistory.map((item) => parseDate(item.effective_date).getTime());
    let bandPath = `M ${x(rangeDates[0]).toFixed(1)} ${y(Number(rangeHistory[0].upper)).toFixed(1)}`;
    for (let index = 1; index < rangeHistory.length; index += 1) {
      bandPath += ` H ${x(rangeDates[index]).toFixed(1)} V ${y(Number(rangeHistory[index].upper)).toFixed(1)}`;
    }
    const last = rangeHistory.length - 1;
    bandPath += ` V ${y(Number(rangeHistory[last].lower)).toFixed(1)}`;
    for (let index = last - 1; index >= 0; index -= 1) {
      bandPath += ` V ${y(Number(rangeHistory[index].lower)).toFixed(1)} H ${x(rangeDates[index]).toFixed(1)}`;
    }
    rangeBand = `${bandPath} Z`;
  }

  const grid = [];
  for (let value = 0; value <= maxValue; value += 1) {
    const position = y(value).toFixed(1);
    grid.push(`<line class="grid" x1="${margin.left}" y1="${position}" x2="${width - margin.right}" y2="${position}"/>`);
    grid.push(`<text class="axis-label" x="${margin.left - 10}" y="${Number(position) + 4}" text-anchor="end">${value}%</text>`);
  }
  const years = [];
  const firstYear = parseDate(history[0].effective_date).getUTCFullYear();
  const lastYear = parseDate(history[history.length - 1].effective_date).getUTCFullYear();
  const interval = Math.max(1, Math.ceil((lastYear - firstYear) / 6));
  for (let year = firstYear; year <= lastYear; year += interval) {
    const position = x(Date.UTC(year, 0, 1)).toFixed(1);
    years.push(`<text class="axis-label" x="${position}" y="${height - 12}" text-anchor="middle">${year}</text>`);
  }

  host.innerHTML = `
    <svg viewBox="0 0 ${width} ${height}" aria-hidden="true">
      <defs><linearGradient id="rateGradient" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#d96c3b" stop-opacity=".22"/><stop offset="1" stop-color="#d96c3b" stop-opacity="0"/></linearGradient></defs>
      ${grid.join('')}
      <path class="rate-area" d="${area}"/>
      ${rangeBand ? `<path class="range-band" d="${rangeBand}"/>` : ''}
      <path class="rate-line" d="${path}"/>
      ${years.join('')}
    </svg>`;
}

const documentLabels = {
  statement_html: '声明',
  implementation_note: '实施说明',
  press_conference: '发布会',
  projections_html: 'SEP',
  minutes_html: '纪要',
};

function renderMeetings(meetings) {
  const host = $('#meetings');
  const now = new Date();
  const past = meetings.meetings
    .filter((item) => meetingAnnouncementTime(item) <= now)
    .slice(-10)
    .reverse();
  const future = meetings.meetings
    .filter((item) => meetingAnnouncementTime(item) > now)
    .slice(0, 8);
  host.innerHTML = '';
  const groups = [
    { title: '最近已结束会议', items: past },
    { title: '未来会议', items: future },
  ];
  for (const group of groups) {
    if (!group.items.length) continue;
    const heading = document.createElement('h3');
    heading.className = 'meeting-group-title';
    heading.textContent = group.title;
    host.appendChild(heading);
    for (const meeting of group.items) {
      const row = document.createElement('article');
      row.className = 'meeting-row';
      const date = document.createElement('div');
      date.className = 'meeting-date';
      date.innerHTML = `${meeting.start_date.slice(0, 7).replace('-', '.')} <small>${meeting.date_label} 日${meeting.has_sep ? ' · 发布 SEP' : ''}</small>`;
      const title = document.createElement('div');
      title.className = 'meeting-title';
      const ended = parseDate(meeting.end_date) < now;
      title.innerHTML = `FOMC ${meeting.is_notation_vote ? '书面表决' : '货币政策会议'}<small>${ended ? '会议已结束' : '计划会议 · 日期可能调整'}</small>`;
      if (meeting.outcome) {
        const outcome = document.createElement('p');
        outcome.className = `meeting-outcome ${meeting.outcome.action}`;
        outcome.textContent = meeting.outcome.summary;
        title.appendChild(outcome);
        if (meeting.outcome.vote) {
          const vote = document.createElement('p');
          vote.className = 'meeting-detail meeting-vote';
          vote.textContent = meeting.outcome.vote.summary;
          title.appendChild(vote);
        }
        if (meeting.outcome.sep) {
          const sep = document.createElement('p');
          sep.className = 'meeting-detail meeting-sep';
          sep.textContent = meeting.outcome.sep.summary;
          sep.title = '政策利率中位数来自美联储 SEP 表格；变化值由相邻两次 SEP 中位数计算。';
          title.appendChild(sep);
        }
        if (meeting.outcome.macro_snapshot) {
          const snapshot = meeting.outcome.macro_snapshot;
          const summaries = snapshot.employment_summary && snapshot.inflation_summary
            ? [snapshot.employment_summary, snapshot.inflation_summary]
            : [snapshot.summary];
          for (const summary of summaries) {
            const macro = document.createElement('p');
            macro.className = 'meeting-macro';
            macro.textContent = summary;
            macro.title = '月份按保守发布滞后选取；历史数值采用 FRED 当前版本，可能包含会后修订。';
            title.appendChild(macro);
          }
        }
      }
      const docs = document.createElement('div');
      docs.className = 'docs';
      let count = 0;
      for (const [key, label] of Object.entries(documentLabels)) {
        if (!meeting.documents[key]) continue;
        const link = document.createElement('a');
        link.className = 'doc';
        link.href = meeting.documents[key];
        link.target = '_blank';
        link.rel = 'noreferrer';
        link.textContent = `${label} ↗`;
        docs.appendChild(link);
        count += 1;
      }
      if (!count) docs.innerHTML = '<span class="pending">等待官方文件</span>';
      row.append(date, title, docs);
      host.appendChild(row);
    }
  }
}

async function init() {
  try {
    const [ratesResponse, meetingsResponse, macroResponse, metadataResponse] = await Promise.all([
      fetch('data/rates.json'), fetch('data/meetings.json'), fetch('data/macro.json'), fetch('data/metadata.json'),
    ]);
    if (!ratesResponse.ok || !meetingsResponse.ok || !macroResponse.ok || !metadataResponse.ok) throw new Error('数据文件不可用');
    const [rates, meetings, macro, metadata] = await Promise.all([
      ratesResponse.json(), meetingsResponse.json(), macroResponse.json(), metadataResponse.json(),
    ]);
    renderMetrics(rates, meetings);
    renderMacroMetrics(macro);
    renderEmploymentChart(macro.history.employment);
    renderInflationChart(macro.history.inflation);
    renderChart(rates.history);
    renderMeetings(meetings);
    $('#version-time').textContent = `数据版本 ${metadata.updated_at.replace('T', ' ').replace('Z', ' UTC')}`;
    $('#data-status').textContent = '官方数据已载入';
  } catch (error) {
    console.error(error);
    $('.status').classList.add('error');
    $('#data-status').textContent = '数据加载失败';
    $('#meetings').innerHTML = '<p class="error-message">暂时无法读取数据，请稍后刷新或查看官方来源。</p>';
  }
}

init();
