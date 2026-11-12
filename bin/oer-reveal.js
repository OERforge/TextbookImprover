/*
 * oer-reveal.js -- what a deck's reveal.js presentation needs to be read
 * and seen whole, written after the script that starts reveal.js by
 * lib/revealtarget.py. Read against reveal.js 6.0.2's js/reveal.js.
 *
 * 1. reveal.js gives the whole presentation role="application", which a
 *    screen reader takes for an application rather than a page to read:
 *    NVDA read a slide's formulas as their letters and its tables cell by
 *    cell. The role goes, so the slide shown is read as a page is, in
 *    browse mode; reveal.js hides the others (aria-hidden, inert). Its
 *    progress bar, a strip a mouse can click to go to a slide, is hidden
 *    from a screen reader too: Chrome gives an element that listens for
 *    clicks a click action, and NVDA shows one with nothing in it as a
 *    space (nvdaHelper's gecko_ia2.cpp), likely the one it read after the
 *    controls.
 * 2. reveal.js announces each slide, and each step of one, in a live
 *    region whose text is the slide's text run together, which loses a
 *    formula's and a table's structure; that region is silenced. As a
 *    slide is shown, its title takes focus instead (the slide itself if it
 *    has none), and as a step appears, what it shows, so a screen reader
 *    reads it and goes on reading from there. A link to a place in the
 *    presentation, a footnote's mark or its note's way back, takes focus
 *    to the place, where reveal.js did nothing for one on the slide shown.
 * 3. A slide taller than the frame is fitted, once its pictures and fonts
 *    are in: its pictures are kept within the frame (oer-reveal.css), and
 *    what's under its title is set closer, then smaller, in the steps
 *    PowerPoint's "Shrink text on overflow" takes, which the deck's
 *    PowerPoint file takes too, to a quarter of its size; one still too
 *    tall scrolls, its keys the page view's (4).
 * 4. A window PAGE_WIDTH pixels wide or less, a phone's, a tablet's held
 *    upright, or a laptop's zoomed past about 130 percent, shows the
 *    slide as a page: reveal.js scales a slide to its window, so zooming
 *    doesn't enlarge its text and a narrow window makes it small. With
 *    reveal.js's layout off, the slide's text is the size it has in the
 *    frame, which zooming enlarges, it reflows to the window's width, and
 *    the page scrolls, the up and down keys, the page keys, home and end,
 *    and space scrolling it as they scroll a page; the left and right keys
 *    go from slide to slide. A slide's page starts at its top, and scrolls
 *    to a step or a link's place as it takes focus; the overview, which
 *    has no page view, is closed.
 * 5. A code block that scrolls, as reveal.js's theme lets one taller than
 *    400 pixels do, or one with a line too long for the slide, takes
 *    keyboard focus, and while it has it the keys of a page's reading
 *    scroll it, the left and right keys too where it scrolls sideways
 *    (WCAG 2.1.1). Which scroll is known only once a slide is laid out:
 *    each is found as the slides are fitted and the page view chosen, and
 *    again as a slide is shown and as the window changes size.
 *
 * Copyright 2026 Robert Szarka
 *
 * This program is free software: you can redistribute it and/or modify
 * it under the terms of the GNU General Public License as published by
 * the Free Software Foundation, either version 3 of the License, or
 * any later version.
 *
 * This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 * GNU General Public License for more details.
 *
 * You should have received a copy of the GNU General Public License
 * along with this program.  If not, see <https://www.gnu.org/licenses/>.
 */
(function () {
  'use strict';
  var deck = window.Reveal;
  if (!deck) { return; }

  // [line spacing, text size]: lines 90 and 80 percent apart, then the
  // text 92.5 percent of its size and down by 7.5 to 25 (pptxtarget's
  // AUTOFIT_STEPS).
  var STEPS = [[0.9, 1], [0.8, 1]];
  for (var size = 92.5; size >= 25; size -= 7.5) { STEPS.push([0.8, size / 100]); }

  function title(slide) {
    var first = slide.firstElementChild;
    return first && /^H[1-6]$/.test(first.tagName) ? first : null;
  }

  function paged() {
    return document.documentElement.classList.contains('oer-page-view');
  }

  // An element given focus, as soon as it can take it: a step's content
  // is hidden still as reveal.js says it's shown, until its fade begins,
  // so it's tried again on the frames after, for half a second. What
  // can't take focus of itself is made to, and marked, for the outline
  // of keyboard focus to be left off it; a link is focused as it is. The
  // page view scrolls to a step or a place (scroll); a slide's page is
  // scrolled to its top as it's shown, and the slides don't scroll, which
  // a slide coming in from the side would shift.
  function focus(element, scroll, tries) {
    if (!element) { return; }
    if (element.tabIndex < 0 && !element.hasAttribute('tabindex')) {
      element.setAttribute('tabindex', '-1');
      element.setAttribute('data-oer-focus', '');
    }
    element.focus({ preventScroll: !scroll });
    var left = tries === undefined ? 30 : tries;
    if (document.activeElement !== element && left > 0) {
      window.requestAnimationFrame(function () { focus(element, scroll, left - 1); });
    }
  }

  // A link to a place in the presentation, a footnote's mark, its note's
  // way back, or a link to a slide: reveal.js shows the place's slide, and
  // does nothing for a place on the slide shown; focus goes to the place,
  // a slide's title for a slide.
  function place(event) {
    var link = event.target.closest ? event.target.closest('a[href^="#"]') : null;
    var element = null;
    try {
      element = link && document.getElementById(
        decodeURIComponent(link.getAttribute('href').replace(/^#\/?/, '')));
    } catch (error) { return; }
    var slide = deck.getCurrentSlide();
    focus(element === slide ? title(slide) || slide : element, paged());
  }

  function fit(slide, height) {
    var heading = title(slide);
    if (heading) { heading.classList.add('oer-title'); }
    if (slide.scrollHeight <= height) { return; }
    slide.classList.add('oer-fitted');
    for (var i = 0; i < STEPS.length; i++) {
      slide.style.setProperty('--oer-line', STEPS[i][0]);
      slide.style.setProperty('--oer-scale', STEPS[i][1]);
      if (slide.scrollHeight <= height) { return; }
    }
    slide.classList.add('oer-scrolled');
  }

  // A code block that scrolls takes focus (5); one that no longer does,
  // in another window, gives back what it was given.
  var CODE = 'pre, pre > code, div.sourceCode';
  var SCROLLS = { auto: true, scroll: true };

  function scrolls(element) {
    var style = window.getComputedStyle(element);
    return (SCROLLS[style.overflowY] === true && element.scrollHeight > element.clientHeight + 1)
      || (SCROLLS[style.overflowX] === true && element.scrollWidth > element.clientWidth + 1);
  }

  function scrollers(slide) {
    Array.prototype.forEach.call(slide.querySelectorAll(CODE), function (element) {
      var given = element.hasAttribute('data-oer-scroller');
      if (scrolls(element)) {
        if (!given && !element.hasAttribute('tabindex')) {
          element.setAttribute('tabindex', '0');
          element.setAttribute('data-oer-scroller', '');
        }
      } else if (given) {
        element.removeAttribute('tabindex');
        element.removeAttribute('data-oer-scroller');
      }
    });
  }

  // Each slide shown for a moment, as reveal.js shows none but the
  // current one and a slide it isn't showing is display: none, with no
  // size to measure.
  function measured(work) {
    deck.getSlides().forEach(function (slide) {
      var shown = slide.style.display;
      slide.style.display = 'block';
      work(slide);
      slide.style.display = shown;
    });
  }

  function fitAll() {
    var height = deck.getConfig().height;
    measured(function (slide) {
      fit(slide, height);
      scrollers(slide);
    });
    deck.layout();
  }

  function loaded() {
    var waits = [document.fonts ? document.fonts.ready : null];
    Array.prototype.forEach.call(deck.getRevealElement().querySelectorAll('img'), function (img) {
      if (!img.complete) {
        waits.push(new Promise(function (done) {
          img.addEventListener('load', done);
          img.addEventListener('error', done);
        }));
      }
    });
    return Promise.all(waits);
  }

  var PAGE_WIDTH = 1000;
  var LAYOUT = ['width', 'height', 'left', 'top', 'right', 'bottom', 'zoom', 'transform'];

  // The page view, or the slides again, which configure lays out. The
  // overview, the slides side by side, has no page view of its own: it's
  // closed and kept closed.
  function pageView() {
    var root = document.documentElement;
    var narrow = window.innerWidth <= PAGE_WIDTH;
    if (narrow === paged()) { return; }
    if (narrow && deck.isOverview()) { deck.toggleOverview(false); }
    root.classList.toggle('oer-page-view', narrow);
    deck.configure({ disableLayout: narrow, overview: !narrow });
    if (narrow) {
      // What reveal.js's layout set, which it leaves when it's turned off.
      var slides = deck.getSlidesElement();
      LAYOUT.forEach(function (name) { slides.style.removeProperty(name); });
    }
  }

  // The keys a page's reading takes, space, page up and down, home and
  // end, and up and down, scroll the narrow window's page and a slide that
  // scrolls, where reveal.js would take them for going from slide to
  // slide; the left and right keys still do that.
  var PAGE_KEYS = { 32: true, 33: true, 34: true, 35: true, 36: true, 38: true, 40: true };
  var SIDE_KEYS = { 37: true, 39: true };

  // A code block that scrolls and has focus takes the page's keys, and
  // the left and right keys where it scrolls sideways (5).
  function inScroller(event) {
    var element = document.activeElement;
    if (!element || !element.hasAttribute('data-oer-scroller')) { return false; }
    return PAGE_KEYS[event.keyCode] === true
      || (SIDE_KEYS[event.keyCode] === true && element.scrollWidth > element.clientWidth + 1);
  }

  function scrolling(event) {
    if (deck.isOverview()) { return false; }
    return inScroller(event) || (PAGE_KEYS[event.keyCode] === true
      && (paged() || deck.getCurrentSlide().classList.contains('oer-scrolled')));
  }

  function start() {
    var presentation = deck.getRevealElement();
    presentation.removeAttribute('role');
    var status = presentation.querySelector('.aria-status');
    if (status) {
      status.removeAttribute('aria-live');
      status.setAttribute('aria-hidden', 'true');
    }
    var progress = presentation.querySelector('.progress');
    if (progress) { progress.setAttribute('aria-hidden', 'true'); }
    deck.configure({ keyboardCondition: function (event) { return !scrolling(event); } });
    deck.on('slidechanged', function (event) {
      scrollers(event.currentSlide);
      if (paged()) { window.scrollTo(0, 0); }
      if (!deck.isOverview()) { focus(title(event.currentSlide) || event.currentSlide, false); }
    });
    deck.on('fragmentshown', function (event) { focus(event.fragment, paged()); });
    deck.getSlidesElement().addEventListener('click', place);
    loaded().then(function () {
      fitAll();
      pageView();
      measured(scrollers);
      window.addEventListener('resize', function () {
        pageView();
        scrollers(deck.getCurrentSlide());
      });
    });
  }

  if (deck.isReady()) { start(); } else { deck.on('ready', start); }
})();
