function setupKeyboardShortcuts() {
  document.addEventListener("keydown", (e) => {
    // Don’t hijack keys while typing
    const el = e.target;
    const isTyping =
      el &&
      (el.tagName === "INPUT" ||
        el.tagName === "TEXTAREA" ||
        el.isContentEditable);

    if (isTyping) return;

    if (!window.ec) return;

    // Left / Right navigation
    if (e.key === "ArrowLeft") {
      e.preventDefault();
      window.ec.prev?.();   // previous period
      return;
    }
    if (e.key === "ArrowRight") {
      e.preventDefault();
      window.ec.next?.();   // next period
      return;
    }

    // Optional: "t" to jump to today
    if (e.key.toLowerCase() === "t") {
      e.preventDefault();
      window.ec.today?.();
      return;
    }
  });
}

function injectHeaderButtonSvgs() {
  const root = document.getElementById("ec");
  if (!root) return;

  // Your provided export icon
  const exportSvg = `<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M17.478 9.011h.022c2.485 0 4.5 2.018 4.5 4.508c0 2.32-1.75 4.232-4 4.481m-.522-8.989q.021-.248.022-.5A5.505 5.505 0 0 0 12 3a5.505 5.505 0 0 0-5.48 5.032m10.958.98a5.5 5.5 0 0 1-1.235 3.005M6.52 8.032A5.006 5.006 0 0 0 2 13.018a5.01 5.01 0 0 0 4 4.91m.52-9.896q.237-.023.48-.023c1.126 0 2.165.373 3 1.002M12 21v-8m0 8c-.7 0-2.008-1.994-2.5-2.5M12 21c.7 0 2.008-1.994 2.5-2.5"/></svg>`;

  // Simple edit/pencil icon (inline SVG)
  const editSvg = `<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M4 20h4l10.5-10.5a2.12 2.12 0 0 0 0-3L16.5 4.5a2.12 2.12 0 0 0-3 0L3 15v5zM13.5 4.5l6 6"/></svg>`;

  // Try a few likely selectors (EventCalendar and FullCalendar variants)
  const exportBtn =
    root.querySelector(".ec-exportBtn-button") ||
    root.querySelector(".fc-exportBtn-button") ||
    findButtonByText(root, "export");

  const editBtn =
    root.querySelector(".ec-editBtn-button") ||
    root.querySelector(".fc-editBtn-button") ||
    findButtonByText(root, "edit");

  if (exportBtn) {
    exportBtn.innerHTML = exportSvg;
    exportBtn.setAttribute("title", "Export");
    exportBtn.setAttribute("aria-label", "Export");
  }

  if (editBtn) {
    editBtn.innerHTML = editSvg;
    editBtn.setAttribute("title", "Edit");
    editBtn.setAttribute("aria-label", "Edit");
  }
}

function findButtonByText(root, txt) {
  const buttons = root.querySelectorAll("button");
  for (const b of buttons) {
    if ((b.textContent || "").trim().toLowerCase() === txt) return b;
  }
  return null;
}

// Toolbar can re-render when changing view / navigating.
// This observer re-applies SVGs when the header changes.
let _toolbarObserver;
function observeToolbarForReplacements() {
  const root = document.getElementById("ec");
  if (!root || _toolbarObserver) return;

  _toolbarObserver = new MutationObserver(() => injectHeaderButtonSvgs());
  _toolbarObserver.observe(root, { childList: true, subtree: true });
}


async function initCalendar() {
  const events = await loadEventsFromICal();
  const ec = new EventCalendar(document.getElementById("ec"), {
    view: "dayGridMonth",
    customButtons: {
      exportBtn: {
        text: "export",
        click: function () {
          generateICal();
        },
      },
      editBtn: {
        text: "edit",
        click: function () {
          window.open(
            "https://github.com/fs-ise/handbook/edit/main/data/events.yaml",
            "_blank",
            "noopener,noreferrer"
          );
        },
      },
    },
    headerToolbar: {
      start: "today,prev,next",
      center: "title",
      end: "dayGridMonth,timeGridWeek,listWeek exportBtn,editBtn",
    },

    // 👇 add these two hooks (see section 2)
    datesSet: function () {
      injectHeaderButtonSvgs();
    },
    viewDidMount: function () {
      injectHeaderButtonSvgs();
    },

    buttonText: {
      close: "Close",
      dayGridMonth: "Month",
      listDay: "list",
      listMonth: "list",
      listWeek: "Schedule",
      listYear: "list",
      resourceTimeGridDay: "resources",
      resourceTimeGridWeek: "resources",
      resourceTimelineDay: "timeline",
      resourceTimelineMonth: "timeline",
      resourceTimelineWeek: "timeline",
      timeGridDay: "day",
      timeGridWeek: "Week",
      today: "Today",
    },
    scrollTime: "09:00:00",
    events: events,
    views: { timeGridWeek: { pointer: true } },
    eventClick: function (info) {
      popUpEvent(info.event);
    },
    dayMaxEvents: true,
    nowIndicator: true,
    eventStartEditable: false,
    hiddenDays: [0, 6],
  });

  window.ec = ec;

  // initial injection (in case hooks above aren’t supported in your build)
  injectHeaderButtonSvgs();
  observeToolbarForReplacements();
}



async function fetchFirstOk(urls) {
  let lastErr;
  for (const url of urls) {
    try {
      const res = await fetch(url, { cache: "no-cache" });
      if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
      return await res.text();
    } catch (err) {
      lastErr = err;
      console.warn("Failed to fetch", url, err);
    }
  }
  throw lastErr || new Error("No URL succeeded");
}

// Parse events from iCal file
async function loadEventsFromICal() {
  try {
    // 1) Prefer local/relative (works when served by your site or local server)
    // Adjust these paths to match where the .ical is in your built site.
    const localCandidates = [
      "./assets/calendar/fs-ise.ical",
      "/assets/calendar/fs-ise.ical",
    ];

    // 2) Fallback: GitHub raw
    const githubRaw =
      "https://raw.githubusercontent.com/fs-ise/handbook/main/assets/calendar/fs-ise.ical";

    const iCalText = await fetchFirstOk([...localCandidates, githubRaw]);

    const jcalData = ICAL.parse(iCalText);
    const vcalendar = new ICAL.Component(jcalData);
    const vevents = vcalendar.getAllSubcomponents("vevent");

    return vevents.map((vevent) => {
      const event = new ICAL.Event(vevent);
      const title = (event.summary || "").toLowerCase();

      // Default: teaching (blue)
      let category = "teaching";
      let color = "#007acc";

      // General
      if (title.includes("vacation") || title.includes("remote work") || title.includes("professorium")) {
        category = "general";
        color = "#C8D1DC";
      }

      // Events
      const eventKeywords = [
        "feier",
        "conference",
        "dies academicus",
        "weihnachtsfeier",
        "end-of-year",
        "choose-a-chair",
      ];
      if (eventKeywords.some((kw) => title.includes(kw))) {
        category = "events";
        color = "#2e7d32";
      }

      return {
        start: event.startDate.toJSDate(),
        end: event.endDate.toJSDate(),
        title: event.summary,
        description: event.description,
        location: event.location,
        category,
        color,
      };
    });
  } catch (error) {
    console.error("Error fetching or parsing iCal file:", error);
    return [];
  }
}

function _pad(num) {
    let norm = Math.floor(Math.abs(num));
    return (norm < 10 ? '0' : '') + norm;
}

function generateICal() {
    const events = ec.getEvents();

    var cal = ics();

    events.forEach(event => {
        cal.addEvent(event.title || " ", event.description || " ", event.location || " ", event.start, event.end);
    });

    const blob = new Blob([cal.toString()], { type: 'text/calendar' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'calendar.ics';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
}

function popUpEvent(event) {
    const startTime = event.start.toLocaleString();
    const endTime = event.end ? event.end.toLocaleString() : 'undefined';

    // modal
    const modal = document.createElement('div');
    modal.style.cssText = `
        position: fixed;
        top: 50%;
        left: 50%;
        transform: translate(-50%, -50%);
        background: white;
        padding: 20px;
        border-radius: 8px;
        box-shadow: 0 2px 10px rgba(0,0,0,0.1);
        z-index: 1000;
        width: 400px;
    `;

    // overlay
    const overlay = document.createElement('div');
    overlay.style.cssText = `
        position: fixed;
        top: 0;
        left: 0;
        right: 0;
        bottom: 0;
        background: rgba(0,0,0,0.5);
        z-index: 999;
    `;

    modal.innerHTML = `
        <div>
            <h3>${event.title}</h3>
            <p>start: ${startTime}</p>
            <p>end: ${endTime}</p>
            <div style="text-align: center; margin-top: 15px;">
                <button onclick="this.closest('div').parentElement.parentElement.remove();document.querySelector('[data-modal-overlay]').remove()">Close</button>
            </div>
        </div>
    `;

    overlay.setAttribute('data-modal-overlay', '');
    document.body.appendChild(overlay);
    document.body.appendChild(modal);
}

document.addEventListener("DOMContentLoaded", async () => {
  await initCalendar();
  setupKeyboardShortcuts();
});
