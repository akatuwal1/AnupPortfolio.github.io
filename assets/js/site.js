/* Motion layer. Everything here is progressive enhancement:
   the page renders its complete final state with no JS, no GSAP,
   or with prefers-reduced-motion set. */
(function () {
	'use strict';

	var reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

	/* ---- count-up stats (vanilla rAF, no library) ---- */
	var counters = document.querySelectorAll('[data-countup]');

	function animateCount(el) {
		var target = parseFloat(el.getAttribute('data-countup'));
		var decimals = parseInt(el.getAttribute('data-decimals') || '0', 10);
		var duration = 1200;
		var start = null;
		function frame(now) {
			if (start === null) start = now;
			var p = Math.min((now - start) / duration, 1);
			var eased = 1 - Math.pow(1 - p, 3);
			el.textContent = (target * eased).toFixed(decimals);
			if (p < 1) {
				requestAnimationFrame(frame);
			} else {
				/* land on the exact value — no rounding drift */
				el.textContent = target.toFixed(decimals);
			}
		}
		requestAnimationFrame(frame);
	}

	if (!reduced && 'IntersectionObserver' in window && counters.length) {
		var io = new IntersectionObserver(function (entries) {
			entries.forEach(function (entry) {
				if (!entry.isIntersecting) return;
				io.unobserve(entry.target);
				animateCount(entry.target);
			});
		}, { threshold: 0.5 });
		counters.forEach(function (el) { io.observe(el); });
	}

	if (reduced) return; /* static end-state for everything below */

	/* Hide the hero now (this runs pre-paint via defer) so GSAP can bring
	   it in; if GSAP hasn't arrived shortly, show the static hero instead. */
	document.documentElement.classList.add('js-anim');
	var heroPlayed = false;
	var heroFallback = setTimeout(function () {
		heroPlayed = true;
		document.documentElement.classList.remove('js-anim');
	}, 2000);

	/* ---- lazy-load GSAP + ScrollTrigger (vendored; never blocks first paint) ---- */
	var VENDOR = 'assets/js/vendor/';
	function loadScript(src) {
		return new Promise(function (resolve, reject) {
			var s = document.createElement('script');
			s.src = src;
			s.async = true;
			s.onload = resolve;
			s.onerror = reject;
			document.head.appendChild(s);
		});
	}

	loadScript(VENDOR + 'gsap.min.js')
		.then(function () { return loadScript(VENDOR + 'ScrollTrigger.min.js'); })
		.then(function () {
			var gsap = window.gsap;
			gsap.registerPlugin(window.ScrollTrigger);

			/* Moment 1: hero entrance — subtle, once, on load */
			if (!heroPlayed) {
				clearTimeout(heroFallback);
				heroPlayed = true;
				gsap.to('[data-hero]', {
					opacity: 1,
					y: 0,
					duration: 0.7,
					ease: 'power2.out',
					stagger: 0.09,
					clearProps: 'all',
					onComplete: function () {
						document.documentElement.classList.remove('js-anim');
					}
				});
			}

			/* Moment 2: the bias chart draws in as it enters the viewport */
			var chartTweens = [
				gsap.from('#bias-chart .bar-fill', {
					scaleX: 0,
					transformOrigin: 'left center',
					duration: 0.9,
					ease: 'power2.out',
					stagger: 0.15,
					scrollTrigger: { trigger: '#bias-chart', start: 'top 78%', once: true }
				}),
				gsap.from('#bias-chart .bar-value', {
					opacity: 0,
					duration: 0.5,
					delay: 0.55,
					stagger: 0.12,
					scrollTrigger: { trigger: '#bias-chart', start: 'top 78%', once: true }
				})
			];

			/* teardown (single-page site: on navigation away) */
			window.addEventListener('pagehide', function () {
				chartTweens.forEach(function (t) {
					if (t.scrollTrigger) t.scrollTrigger.kill();
					t.kill();
				});
			}, { once: true });
		})
		.catch(function () {
			/* CDN unavailable: static site, no motion */
			clearTimeout(heroFallback);
			document.documentElement.classList.remove('js-anim');
		});
})();
