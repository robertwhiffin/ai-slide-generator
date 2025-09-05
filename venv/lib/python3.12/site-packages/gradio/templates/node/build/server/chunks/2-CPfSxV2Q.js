import { n as noop, l as get_store_value, c as create_ssr_component, s as subscribe, g as getContext, e as escape, h as add_styles, d as add_attribute, f as each, v as validate_component, m as missing_component, b as createEventDispatcher, j as null_to_empty, o as onDestroy, B as compute_rest_props, C as spread, E as escape_object, D as escape_attribute_value, k as setContext } from './ssr-C3HYbsxA.js';
import { d as derived, w as writable } from './index-ClteBeTX.js';
import { t as tick, b as binding_callbacks, a as bind } from './Component-NmRBwSfF.js';
import require$$2 from 'path';
import require$$1$1 from 'url';
import require$$1 from 'fs';

const s$2=!1,a$2=!1;

const is_client = typeof window !== 'undefined';

/** @type {() => number} */
let now = is_client ? () => window.performance.now() : () => Date.now();

let raf = is_client ? (cb) => requestAnimationFrame(cb) : noop;

const tasks = new Set();

/**
 * @param {number} now
 * @returns {void}
 */
function run_tasks(now) {
	tasks.forEach((task) => {
		if (!task.c(now)) {
			tasks.delete(task);
			task.f();
		}
	});
	if (tasks.size !== 0) raf(run_tasks);
}

/**
 * Creates a new task that runs on each raf frame
 * until it returns a falsy value or is aborted
 * @param {import('./private.js').TaskCallback} callback
 * @returns {import('./private.js').Task}
 */
function loop(callback) {
	/** @type {import('./private.js').TaskEntry} */
	let task;
	if (tasks.size === 0) raf(run_tasks);
	return {
		promise: new Promise((fulfill) => {
			tasks.add((task = { c: callback, f: fulfill }));
		}),
		abort() {
			tasks.delete(task);
		}
	};
}

/** @type {typeof globalThis} */
const globals =
	typeof window !== 'undefined'
		? window
		: typeof globalThis !== 'undefined'
		? globalThis
		: // @ts-ignore Node typings have this
		  global;

/** regex of all html void element names */
const void_element_names =
	/^(?:area|base|br|col|command|embed|hr|img|input|keygen|link|meta|param|source|track|wbr)$/;

/**
 * @param {string} name
 * @returns {boolean}
 */
function is_void(name) {
	return void_element_names.test(name) || name.toLowerCase() === '!doctype';
}

var qs=typeof globalThis<"u"?globalThis:typeof window<"u"?window:typeof global<"u"?global:typeof self<"u"?self:{};function Ir$1(e){return e&&e.__esModule&&Object.prototype.hasOwnProperty.call(e,"default")?e.default:e}function Qs(e){if(e.__esModule)return e;var t=e.default;if(typeof t=="function"){var n=function r(){return this instanceof r?Reflect.construct(t,arguments,this.constructor):t.apply(this,arguments)};n.prototype=t.prototype;}else n={};return Object.defineProperty(n,"__esModule",{value:!0}),Object.keys(e).forEach(function(r){var i=Object.getOwnPropertyDescriptor(e,r);Object.defineProperty(n,r,i.get?i:{enumerable:!0,get:function(){return e[r]}});}),n}const Tr$1="data:image/svg+xml,%3csvg%20xmlns='http://www.w3.org/2000/svg'%20width='10'%20height='10'%20fill='none'%3e%3cpath%20fill='%23FF3270'%20d='M1.93%206.03v2.04h2.04V6.03H1.93Z'/%3e%3cpath%20fill='%23861FFF'%20d='M6.03%206.03v2.04h2.04V6.03H6.03Z'/%3e%3cpath%20fill='%23097EFF'%20d='M1.93%201.93v2.04h2.04V1.93H1.93Z'/%3e%3cpath%20fill='%23000'%20fill-rule='evenodd'%20d='M.5%201.4c0-.5.4-.9.9-.9h3.1a.9.9%200%200%201%20.87.67A2.44%202.44%200%200%201%209.5%202.95c0%20.65-.25%201.24-.67%201.68.39.1.67.46.67.88v3.08c0%20.5-.4.91-.9.91H1.4a.9.9%200%200%201-.9-.9V1.4Zm1.43.53v2.04h2.04V1.93H1.93Zm0%206.14V6.03h2.04v2.04H1.93Zm4.1%200V6.03h2.04v2.04H6.03Zm0-5.12a1.02%201.02%200%201%201%202.04%200%201.02%201.02%200%200%201-2.04%200Z'%20clip-rule='evenodd'/%3e%3cpath%20fill='%23FFD702'%20d='M7.05%201.93a1.02%201.02%200%201%200%200%202.04%201.02%201.02%200%200%200%200-2.04Z'/%3e%3c/svg%3e";var Or$1=function(t){return Hr$1(t)&&!Pr$1(t)};function Hr$1(e){return !!e&&typeof e=="object"}function Pr$1(e){var t=Object.prototype.toString.call(e);return t==="[object RegExp]"||t==="[object Date]"||Lr$1(e)}var Nr$1=typeof Symbol=="function"&&Symbol.for,Mr$1=Nr$1?Symbol.for("react.element"):60103;function Lr$1(e){return e.$$typeof===Mr$1}function Rr$1(e){return Array.isArray(e)?[]:{}}function Le$3(e,t){return t.clone!==!1&&t.isMergeableObject(e)?ye$1(Rr$1(e),e,t):e}function kr$1(e,t,n){return e.concat(t).map(function(r){return Le$3(r,n)})}function Dr$1(e,t){if(!t.customMerge)return ye$1;var n=t.customMerge(e);return typeof n=="function"?n:ye$1}function Ur$1(e){return Object.getOwnPropertySymbols?Object.getOwnPropertySymbols(e).filter(function(t){return Object.propertyIsEnumerable.call(e,t)}):[]}function Mt(e){return Object.keys(e).concat(Ur$1(e))}function _n$1(e,t){try{return t in e}catch{return !1}}function jr$1(e,t){return _n$1(e,t)&&!(Object.hasOwnProperty.call(e,t)&&Object.propertyIsEnumerable.call(e,t))}function Gr$1(e,t,n){var r={};return n.isMergeableObject(e)&&Mt(e).forEach(function(i){r[i]=Le$3(e[i],n);}),Mt(t).forEach(function(i){jr$1(e,i)||(_n$1(e,i)&&n.isMergeableObject(t[i])?r[i]=Dr$1(i,n)(e[i],t[i],n):r[i]=Le$3(t[i],n));}),r}function ye$1(e,t,n){n=n||{},n.arrayMerge=n.arrayMerge||kr$1,n.isMergeableObject=n.isMergeableObject||Or$1,n.cloneUnlessOtherwiseSpecified=Le$3;var r=Array.isArray(t),i=Array.isArray(e),o=r===i;return o?r?n.arrayMerge(e,t,n):Gr$1(e,t,n):Le$3(t,n)}ye$1.all=function(t,n){if(!Array.isArray(t))throw new Error("first argument should be an array");return t.reduce(function(r,i){return ye$1(r,i,n)},{})};var Fr$1=ye$1,zr$1=Fr$1;const $r$1=Ir$1(zr$1);var ft$1=function(e,t){return ft$1=Object.setPrototypeOf||{__proto__:[]}instanceof Array&&function(n,r){n.__proto__=r;}||function(n,r){for(var i in r)Object.prototype.hasOwnProperty.call(r,i)&&(n[i]=r[i]);},ft$1(e,t)};function Ve$1(e,t){if(typeof t!="function"&&t!==null)throw new TypeError("Class extends value "+String(t)+" is not a constructor or null");ft$1(e,t);function n(){this.constructor=e;}e.prototype=t===null?Object.create(t):(n.prototype=t.prototype,new n);}var I=function(){return I=Object.assign||function(t){for(var n,r=1,i=arguments.length;r<i;r++){n=arguments[r];for(var o in n)Object.prototype.hasOwnProperty.call(n,o)&&(t[o]=n[o]);}return t},I.apply(this,arguments)};function Wr$1(e,t){var n={};for(var r in e)Object.prototype.hasOwnProperty.call(e,r)&&t.indexOf(r)<0&&(n[r]=e[r]);if(e!=null&&typeof Object.getOwnPropertySymbols=="function")for(var i=0,r=Object.getOwnPropertySymbols(e);i<r.length;i++)t.indexOf(r[i])<0&&Object.prototype.propertyIsEnumerable.call(e,r[i])&&(n[r[i]]=e[r[i]]);return n}function et$3(e,t,n){if(arguments.length===2)for(var r=0,i=t.length,o;r<i;r++)(o||!(r in t))&&(o||(o=Array.prototype.slice.call(t,0,r)),o[r]=t[r]);return e.concat(o||Array.prototype.slice.call(t))}function tt$2(e,t){var n=t&&t.cache?t.cache:Yr$1,r=t&&t.serializer?t.serializer:Kr$1,i=t&&t.strategy?t.strategy:qr$1;return i(e,{cache:n,serializer:r})}function Vr$1(e){return e==null||typeof e=="number"||typeof e=="boolean"}function gn(e,t,n,r){var i=Vr$1(r)?r:n(r),o=t.get(i);return typeof o>"u"&&(o=e.call(this,r),t.set(i,o)),o}function bn$1(e,t,n){var r=Array.prototype.slice.call(arguments,3),i=n(r),o=t.get(i);return typeof o>"u"&&(o=e.apply(this,r),t.set(i,o)),o}function yt$3(e,t,n,r,i){return n.bind(t,e,r,i)}function qr$1(e,t){var n=e.length===1?gn:bn$1;return yt$3(e,this,n,t.cache.create(),t.serializer)}function Qr$1(e,t){return yt$3(e,this,bn$1,t.cache.create(),t.serializer)}function Xr$1(e,t){return yt$3(e,this,gn,t.cache.create(),t.serializer)}var Kr$1=function(){return JSON.stringify(arguments)},Zr$1=function(){function e(){this.cache=Object.create(null);}return e.prototype.get=function(t){return this.cache[t]},e.prototype.set=function(t,n){this.cache[t]=n;},e}(),Yr$1={create:function(){return new Zr$1}},nt$3={variadic:Qr$1,monadic:Xr$1},x$2;(function(e){e[e.EXPECT_ARGUMENT_CLOSING_BRACE=1]="EXPECT_ARGUMENT_CLOSING_BRACE",e[e.EMPTY_ARGUMENT=2]="EMPTY_ARGUMENT",e[e.MALFORMED_ARGUMENT=3]="MALFORMED_ARGUMENT",e[e.EXPECT_ARGUMENT_TYPE=4]="EXPECT_ARGUMENT_TYPE",e[e.INVALID_ARGUMENT_TYPE=5]="INVALID_ARGUMENT_TYPE",e[e.EXPECT_ARGUMENT_STYLE=6]="EXPECT_ARGUMENT_STYLE",e[e.INVALID_NUMBER_SKELETON=7]="INVALID_NUMBER_SKELETON",e[e.INVALID_DATE_TIME_SKELETON=8]="INVALID_DATE_TIME_SKELETON",e[e.EXPECT_NUMBER_SKELETON=9]="EXPECT_NUMBER_SKELETON",e[e.EXPECT_DATE_TIME_SKELETON=10]="EXPECT_DATE_TIME_SKELETON",e[e.UNCLOSED_QUOTE_IN_ARGUMENT_STYLE=11]="UNCLOSED_QUOTE_IN_ARGUMENT_STYLE",e[e.EXPECT_SELECT_ARGUMENT_OPTIONS=12]="EXPECT_SELECT_ARGUMENT_OPTIONS",e[e.EXPECT_PLURAL_ARGUMENT_OFFSET_VALUE=13]="EXPECT_PLURAL_ARGUMENT_OFFSET_VALUE",e[e.INVALID_PLURAL_ARGUMENT_OFFSET_VALUE=14]="INVALID_PLURAL_ARGUMENT_OFFSET_VALUE",e[e.EXPECT_SELECT_ARGUMENT_SELECTOR=15]="EXPECT_SELECT_ARGUMENT_SELECTOR",e[e.EXPECT_PLURAL_ARGUMENT_SELECTOR=16]="EXPECT_PLURAL_ARGUMENT_SELECTOR",e[e.EXPECT_SELECT_ARGUMENT_SELECTOR_FRAGMENT=17]="EXPECT_SELECT_ARGUMENT_SELECTOR_FRAGMENT",e[e.EXPECT_PLURAL_ARGUMENT_SELECTOR_FRAGMENT=18]="EXPECT_PLURAL_ARGUMENT_SELECTOR_FRAGMENT",e[e.INVALID_PLURAL_ARGUMENT_SELECTOR=19]="INVALID_PLURAL_ARGUMENT_SELECTOR",e[e.DUPLICATE_PLURAL_ARGUMENT_SELECTOR=20]="DUPLICATE_PLURAL_ARGUMENT_SELECTOR",e[e.DUPLICATE_SELECT_ARGUMENT_SELECTOR=21]="DUPLICATE_SELECT_ARGUMENT_SELECTOR",e[e.MISSING_OTHER_CLAUSE=22]="MISSING_OTHER_CLAUSE",e[e.INVALID_TAG=23]="INVALID_TAG",e[e.INVALID_TAG_NAME=25]="INVALID_TAG_NAME",e[e.UNMATCHED_CLOSING_TAG=26]="UNMATCHED_CLOSING_TAG",e[e.UNCLOSED_TAG=27]="UNCLOSED_TAG";})(x$2||(x$2={}));var M;(function(e){e[e.literal=0]="literal",e[e.argument=1]="argument",e[e.number=2]="number",e[e.date=3]="date",e[e.time=4]="time",e[e.select=5]="select",e[e.plural=6]="plural",e[e.pound=7]="pound",e[e.tag=8]="tag";})(M||(M={}));var we$2;(function(e){e[e.number=0]="number",e[e.dateTime=1]="dateTime";})(we$2||(we$2={}));function Lt$2(e){return e.type===M.literal}function Jr$1(e){return e.type===M.argument}function vn(e){return e.type===M.number}function yn(e){return e.type===M.date}function wn(e){return e.type===M.time}function Cn(e){return e.type===M.select}function En(e){return e.type===M.plural}function ei(e){return e.type===M.pound}function xn(e){return e.type===M.tag}function Sn(e){return !!(e&&typeof e=="object"&&e.type===we$2.number)}function ht$1(e){return !!(e&&typeof e=="object"&&e.type===we$2.dateTime)}var Bn=/[ \xA0\u1680\u2000-\u200A\u202F\u205F\u3000]/,ti=/(?:[Eec]{1,6}|G{1,5}|[Qq]{1,5}|(?:[yYur]+|U{1,5})|[ML]{1,5}|d{1,2}|D{1,3}|F{1}|[abB]{1,5}|[hkHK]{1,2}|w{1,2}|W{1}|m{1,2}|s{1,2}|[zZOvVxX]{1,4})(?=([^']*'[^']*')*[^']*$)/g;function ni(e){var t={};return e.replace(ti,function(n){var r=n.length;switch(n[0]){case"G":t.era=r===4?"long":r===5?"narrow":"short";break;case"y":t.year=r===2?"2-digit":"numeric";break;case"Y":case"u":case"U":case"r":throw new RangeError("`Y/u/U/r` (year) patterns are not supported, use `y` instead");case"q":case"Q":throw new RangeError("`q/Q` (quarter) patterns are not supported");case"M":case"L":t.month=["numeric","2-digit","short","long","narrow"][r-1];break;case"w":case"W":throw new RangeError("`w/W` (week) patterns are not supported");case"d":t.day=["numeric","2-digit"][r-1];break;case"D":case"F":case"g":throw new RangeError("`D/F/g` (day) patterns are not supported, use `d` instead");case"E":t.weekday=r===4?"long":r===5?"narrow":"short";break;case"e":if(r<4)throw new RangeError("`e..eee` (weekday) patterns are not supported");t.weekday=["short","long","narrow","short"][r-4];break;case"c":if(r<4)throw new RangeError("`c..ccc` (weekday) patterns are not supported");t.weekday=["short","long","narrow","short"][r-4];break;case"a":t.hour12=!0;break;case"b":case"B":throw new RangeError("`b/B` (period) patterns are not supported, use `a` instead");case"h":t.hourCycle="h12",t.hour=["numeric","2-digit"][r-1];break;case"H":t.hourCycle="h23",t.hour=["numeric","2-digit"][r-1];break;case"K":t.hourCycle="h11",t.hour=["numeric","2-digit"][r-1];break;case"k":t.hourCycle="h24",t.hour=["numeric","2-digit"][r-1];break;case"j":case"J":case"C":throw new RangeError("`j/J/C` (hour) patterns are not supported, use `h/H/K/k` instead");case"m":t.minute=["numeric","2-digit"][r-1];break;case"s":t.second=["numeric","2-digit"][r-1];break;case"S":case"A":throw new RangeError("`S/A` (second) patterns are not supported, use `s` instead");case"z":t.timeZoneName=r<4?"short":"long";break;case"Z":case"O":case"v":case"V":case"X":case"x":throw new RangeError("`Z/O/v/V/X/x` (timeZone) patterns are not supported, use `z` instead")}return ""}),t}var ri=/[\t-\r \x85\u200E\u200F\u2028\u2029]/i;function ii(e){if(e.length===0)throw new Error("Number skeleton cannot be empty");for(var t=e.split(ri).filter(function(h){return h.length>0}),n=[],r=0,i=t;r<i.length;r++){var o=i[r],s=o.split("/");if(s.length===0)throw new Error("Invalid number skeleton");for(var a=s[0],u=s.slice(1),c=0,l=u;c<l.length;c++){var f=l[c];if(f.length===0)throw new Error("Invalid number skeleton")}n.push({stem:a,options:u});}return n}function oi(e){return e.replace(/^(.*?)-/,"")}var Rt$2=/^\.(?:(0+)(\*)?|(#+)|(0+)(#+))$/g,In=/^(@+)?(\+|#+)?[rs]?$/g,si=/(\*)(0+)|(#+)(0+)|(0+)/g,Tn=/^(0+)$/;function kt$2(e){var t={};return e[e.length-1]==="r"?t.roundingPriority="morePrecision":e[e.length-1]==="s"&&(t.roundingPriority="lessPrecision"),e.replace(In,function(n,r,i){return typeof i!="string"?(t.minimumSignificantDigits=r.length,t.maximumSignificantDigits=r.length):i==="+"?t.minimumSignificantDigits=r.length:r[0]==="#"?t.maximumSignificantDigits=r.length:(t.minimumSignificantDigits=r.length,t.maximumSignificantDigits=r.length+(typeof i=="string"?i.length:0)),""}),t}function On(e){switch(e){case"sign-auto":return {signDisplay:"auto"};case"sign-accounting":case"()":return {currencySign:"accounting"};case"sign-always":case"+!":return {signDisplay:"always"};case"sign-accounting-always":case"()!":return {signDisplay:"always",currencySign:"accounting"};case"sign-except-zero":case"+?":return {signDisplay:"exceptZero"};case"sign-accounting-except-zero":case"()?":return {signDisplay:"exceptZero",currencySign:"accounting"};case"sign-never":case"+_":return {signDisplay:"never"}}}function ai(e){var t;if(e[0]==="E"&&e[1]==="E"?(t={notation:"engineering"},e=e.slice(2)):e[0]==="E"&&(t={notation:"scientific"},e=e.slice(1)),t){var n=e.slice(0,2);if(n==="+!"?(t.signDisplay="always",e=e.slice(2)):n==="+?"&&(t.signDisplay="exceptZero",e=e.slice(2)),!Tn.test(e))throw new Error("Malformed concise eng/scientific notation");t.minimumIntegerDigits=e.length;}return t}function Dt$2(e){var t={},n=On(e);return n||t}function li(e){for(var t={},n=0,r=e;n<r.length;n++){var i=r[n];switch(i.stem){case"percent":case"%":t.style="percent";continue;case"%x100":t.style="percent",t.scale=100;continue;case"currency":t.style="currency",t.currency=i.options[0];continue;case"group-off":case",_":t.useGrouping=!1;continue;case"precision-integer":case".":t.maximumFractionDigits=0;continue;case"measure-unit":case"unit":t.style="unit",t.unit=oi(i.options[0]);continue;case"compact-short":case"K":t.notation="compact",t.compactDisplay="short";continue;case"compact-long":case"KK":t.notation="compact",t.compactDisplay="long";continue;case"scientific":t=I(I(I({},t),{notation:"scientific"}),i.options.reduce(function(u,c){return I(I({},u),Dt$2(c))},{}));continue;case"engineering":t=I(I(I({},t),{notation:"engineering"}),i.options.reduce(function(u,c){return I(I({},u),Dt$2(c))},{}));continue;case"notation-simple":t.notation="standard";continue;case"unit-width-narrow":t.currencyDisplay="narrowSymbol",t.unitDisplay="narrow";continue;case"unit-width-short":t.currencyDisplay="code",t.unitDisplay="short";continue;case"unit-width-full-name":t.currencyDisplay="name",t.unitDisplay="long";continue;case"unit-width-iso-code":t.currencyDisplay="symbol";continue;case"scale":t.scale=parseFloat(i.options[0]);continue;case"rounding-mode-floor":t.roundingMode="floor";continue;case"rounding-mode-ceiling":t.roundingMode="ceil";continue;case"rounding-mode-down":t.roundingMode="trunc";continue;case"rounding-mode-up":t.roundingMode="expand";continue;case"rounding-mode-half-even":t.roundingMode="halfEven";continue;case"rounding-mode-half-down":t.roundingMode="halfTrunc";continue;case"rounding-mode-half-up":t.roundingMode="halfExpand";continue;case"integer-width":if(i.options.length>1)throw new RangeError("integer-width stems only accept a single optional option");i.options[0].replace(si,function(u,c,l,f,h,_){if(c)t.minimumIntegerDigits=l.length;else {if(f&&h)throw new Error("We currently do not support maximum integer digits");if(_)throw new Error("We currently do not support exact integer digits")}return ""});continue}if(Tn.test(i.stem)){t.minimumIntegerDigits=i.stem.length;continue}if(Rt$2.test(i.stem)){if(i.options.length>1)throw new RangeError("Fraction-precision stems only accept a single optional option");i.stem.replace(Rt$2,function(u,c,l,f,h,_){return l==="*"?t.minimumFractionDigits=c.length:f&&f[0]==="#"?t.maximumFractionDigits=f.length:h&&_?(t.minimumFractionDigits=h.length,t.maximumFractionDigits=h.length+_.length):(t.minimumFractionDigits=c.length,t.maximumFractionDigits=c.length),""});var o=i.options[0];o==="w"?t=I(I({},t),{trailingZeroDisplay:"stripIfInteger"}):o&&(t=I(I({},t),kt$2(o)));continue}if(In.test(i.stem)){t=I(I({},t),kt$2(i.stem));continue}var s=On(i.stem);s&&(t=I(I({},t),s));var a=ai(i.stem);a&&(t=I(I({},t),a));}return t}var Ue$1={"001":["H","h"],419:["h","H","hB","hb"],AC:["H","h","hb","hB"],AD:["H","hB"],AE:["h","hB","hb","H"],AF:["H","hb","hB","h"],AG:["h","hb","H","hB"],AI:["H","h","hb","hB"],AL:["h","H","hB"],AM:["H","hB"],AO:["H","hB"],AR:["h","H","hB","hb"],AS:["h","H"],AT:["H","hB"],AU:["h","hb","H","hB"],AW:["H","hB"],AX:["H"],AZ:["H","hB","h"],BA:["H","hB","h"],BB:["h","hb","H","hB"],BD:["h","hB","H"],BE:["H","hB"],BF:["H","hB"],BG:["H","hB","h"],BH:["h","hB","hb","H"],BI:["H","h"],BJ:["H","hB"],BL:["H","hB"],BM:["h","hb","H","hB"],BN:["hb","hB","h","H"],BO:["h","H","hB","hb"],BQ:["H"],BR:["H","hB"],BS:["h","hb","H","hB"],BT:["h","H"],BW:["H","h","hb","hB"],BY:["H","h"],BZ:["H","h","hb","hB"],CA:["h","hb","H","hB"],CC:["H","h","hb","hB"],CD:["hB","H"],CF:["H","h","hB"],CG:["H","hB"],CH:["H","hB","h"],CI:["H","hB"],CK:["H","h","hb","hB"],CL:["h","H","hB","hb"],CM:["H","h","hB"],CN:["H","hB","hb","h"],CO:["h","H","hB","hb"],CP:["H"],CR:["h","H","hB","hb"],CU:["h","H","hB","hb"],CV:["H","hB"],CW:["H","hB"],CX:["H","h","hb","hB"],CY:["h","H","hb","hB"],CZ:["H"],DE:["H","hB"],DG:["H","h","hb","hB"],DJ:["h","H"],DK:["H"],DM:["h","hb","H","hB"],DO:["h","H","hB","hb"],DZ:["h","hB","hb","H"],EA:["H","h","hB","hb"],EC:["h","H","hB","hb"],EE:["H","hB"],EG:["h","hB","hb","H"],EH:["h","hB","hb","H"],ER:["h","H"],ES:["H","hB","h","hb"],ET:["hB","hb","h","H"],FI:["H"],FJ:["h","hb","H","hB"],FK:["H","h","hb","hB"],FM:["h","hb","H","hB"],FO:["H","h"],FR:["H","hB"],GA:["H","hB"],GB:["H","h","hb","hB"],GD:["h","hb","H","hB"],GE:["H","hB","h"],GF:["H","hB"],GG:["H","h","hb","hB"],GH:["h","H"],GI:["H","h","hb","hB"],GL:["H","h"],GM:["h","hb","H","hB"],GN:["H","hB"],GP:["H","hB"],GQ:["H","hB","h","hb"],GR:["h","H","hb","hB"],GT:["h","H","hB","hb"],GU:["h","hb","H","hB"],GW:["H","hB"],GY:["h","hb","H","hB"],HK:["h","hB","hb","H"],HN:["h","H","hB","hb"],HR:["H","hB"],HU:["H","h"],IC:["H","h","hB","hb"],ID:["H"],IE:["H","h","hb","hB"],IL:["H","hB"],IM:["H","h","hb","hB"],IN:["h","H"],IO:["H","h","hb","hB"],IQ:["h","hB","hb","H"],IR:["hB","H"],IS:["H"],IT:["H","hB"],JE:["H","h","hb","hB"],JM:["h","hb","H","hB"],JO:["h","hB","hb","H"],JP:["H","K","h"],KE:["hB","hb","H","h"],KG:["H","h","hB","hb"],KH:["hB","h","H","hb"],KI:["h","hb","H","hB"],KM:["H","h","hB","hb"],KN:["h","hb","H","hB"],KP:["h","H","hB","hb"],KR:["h","H","hB","hb"],KW:["h","hB","hb","H"],KY:["h","hb","H","hB"],KZ:["H","hB"],LA:["H","hb","hB","h"],LB:["h","hB","hb","H"],LC:["h","hb","H","hB"],LI:["H","hB","h"],LK:["H","h","hB","hb"],LR:["h","hb","H","hB"],LS:["h","H"],LT:["H","h","hb","hB"],LU:["H","h","hB"],LV:["H","hB","hb","h"],LY:["h","hB","hb","H"],MA:["H","h","hB","hb"],MC:["H","hB"],MD:["H","hB"],ME:["H","hB","h"],MF:["H","hB"],MG:["H","h"],MH:["h","hb","H","hB"],MK:["H","h","hb","hB"],ML:["H"],MM:["hB","hb","H","h"],MN:["H","h","hb","hB"],MO:["h","hB","hb","H"],MP:["h","hb","H","hB"],MQ:["H","hB"],MR:["h","hB","hb","H"],MS:["H","h","hb","hB"],MT:["H","h"],MU:["H","h"],MV:["H","h"],MW:["h","hb","H","hB"],MX:["h","H","hB","hb"],MY:["hb","hB","h","H"],MZ:["H","hB"],NA:["h","H","hB","hb"],NC:["H","hB"],NE:["H"],NF:["H","h","hb","hB"],NG:["H","h","hb","hB"],NI:["h","H","hB","hb"],NL:["H","hB"],NO:["H","h"],NP:["H","h","hB"],NR:["H","h","hb","hB"],NU:["H","h","hb","hB"],NZ:["h","hb","H","hB"],OM:["h","hB","hb","H"],PA:["h","H","hB","hb"],PE:["h","H","hB","hb"],PF:["H","h","hB"],PG:["h","H"],PH:["h","hB","hb","H"],PK:["h","hB","H"],PL:["H","h"],PM:["H","hB"],PN:["H","h","hb","hB"],PR:["h","H","hB","hb"],PS:["h","hB","hb","H"],PT:["H","hB"],PW:["h","H"],PY:["h","H","hB","hb"],QA:["h","hB","hb","H"],RE:["H","hB"],RO:["H","hB"],RS:["H","hB","h"],RU:["H"],RW:["H","h"],SA:["h","hB","hb","H"],SB:["h","hb","H","hB"],SC:["H","h","hB"],SD:["h","hB","hb","H"],SE:["H"],SG:["h","hb","H","hB"],SH:["H","h","hb","hB"],SI:["H","hB"],SJ:["H"],SK:["H"],SL:["h","hb","H","hB"],SM:["H","h","hB"],SN:["H","h","hB"],SO:["h","H"],SR:["H","hB"],SS:["h","hb","H","hB"],ST:["H","hB"],SV:["h","H","hB","hb"],SX:["H","h","hb","hB"],SY:["h","hB","hb","H"],SZ:["h","hb","H","hB"],TA:["H","h","hb","hB"],TC:["h","hb","H","hB"],TD:["h","H","hB"],TF:["H","h","hB"],TG:["H","hB"],TH:["H","h"],TJ:["H","h"],TL:["H","hB","hb","h"],TM:["H","h"],TN:["h","hB","hb","H"],TO:["h","H"],TR:["H","hB"],TT:["h","hb","H","hB"],TW:["hB","hb","h","H"],TZ:["hB","hb","H","h"],UA:["H","hB","h"],UG:["hB","hb","H","h"],UM:["h","hb","H","hB"],US:["h","hb","H","hB"],UY:["h","H","hB","hb"],UZ:["H","hB","h"],VA:["H","h","hB"],VC:["h","hb","H","hB"],VE:["h","H","hB","hb"],VG:["h","hb","H","hB"],VI:["h","hb","H","hB"],VN:["H","h"],VU:["h","H"],WF:["H","hB"],WS:["h","H"],XK:["H","hB","h"],YE:["h","hB","hb","H"],YT:["H","hB"],ZA:["H","h","hb","hB"],ZM:["h","hb","H","hB"],ZW:["H","h"],"af-ZA":["H","h","hB","hb"],"ar-001":["h","hB","hb","H"],"ca-ES":["H","h","hB"],"en-001":["h","hb","H","hB"],"en-HK":["h","hb","H","hB"],"en-IL":["H","h","hb","hB"],"en-MY":["h","hb","H","hB"],"es-BR":["H","h","hB","hb"],"es-ES":["H","h","hB","hb"],"es-GQ":["H","h","hB","hb"],"fr-CA":["H","h","hB"],"gl-ES":["H","h","hB"],"gu-IN":["hB","hb","h","H"],"hi-IN":["hB","h","H"],"it-CH":["H","h","hB"],"it-IT":["H","h","hB"],"kn-IN":["hB","h","H"],"ml-IN":["hB","h","H"],"mr-IN":["hB","hb","h","H"],"pa-IN":["hB","hb","h","H"],"ta-IN":["hB","h","hb","H"],"te-IN":["hB","h","H"],"zu-ZA":["H","hB","hb","h"]};function ci(e,t){for(var n="",r=0;r<e.length;r++){var i=e.charAt(r);if(i==="j"){for(var o=0;r+1<e.length&&e.charAt(r+1)===i;)o++,r++;var s=1+(o&1),a=o<2?1:3+(o>>1),u="a",c=ui(t);for((c=="H"||c=="k")&&(a=0);a-- >0;)n+=u;for(;s-- >0;)n=c+n;}else i==="J"?n+="H":n+=i;}return n}function ui(e){var t=e.hourCycle;if(t===void 0&&e.hourCycles&&e.hourCycles.length&&(t=e.hourCycles[0]),t)switch(t){case"h24":return "k";case"h23":return "H";case"h12":return "h";case"h11":return "K";default:throw new Error("Invalid hourCycle")}var n=e.language,r;n!=="root"&&(r=e.maximize().region);var i=Ue$1[r||""]||Ue$1[n||""]||Ue$1["".concat(n,"-001")]||Ue$1["001"];return i[0]}var rt$3,fi=new RegExp("^".concat(Bn.source,"*")),hi=new RegExp("".concat(Bn.source,"*$"));function S$1(e,t){return {start:e,end:t}}var pi=!!String.prototype.startsWith&&"_a".startsWith("a",1),di=!!String.fromCodePoint,mi=!!Object.fromEntries,Ai=!!String.prototype.codePointAt,_i=!!String.prototype.trimStart,gi=!!String.prototype.trimEnd,bi=!!Number.isSafeInteger,vi=bi?Number.isSafeInteger:function(e){return typeof e=="number"&&isFinite(e)&&Math.floor(e)===e&&Math.abs(e)<=9007199254740991},pt$2=!0;try{var yi=Pn("([^\\p{White_Space}\\p{Pattern_Syntax}]*)","yu");pt$2=((rt$3=yi.exec("a"))===null||rt$3===void 0?void 0:rt$3[0])==="a";}catch{pt$2=!1;}var Ut$1=pi?function(t,n,r){return t.startsWith(n,r)}:function(t,n,r){return t.slice(r,r+n.length)===n},dt$3=di?String.fromCodePoint:function(){for(var t=[],n=0;n<arguments.length;n++)t[n]=arguments[n];for(var r="",i=t.length,o=0,s;i>o;){if(s=t[o++],s>1114111)throw RangeError(s+" is not a valid code point");r+=s<65536?String.fromCharCode(s):String.fromCharCode(((s-=65536)>>10)+55296,s%1024+56320);}return r},jt$1=mi?Object.fromEntries:function(t){for(var n={},r=0,i=t;r<i.length;r++){var o=i[r],s=o[0],a=o[1];n[s]=a;}return n},Hn=Ai?function(t,n){return t.codePointAt(n)}:function(t,n){var r=t.length;if(!(n<0||n>=r)){var i=t.charCodeAt(n),o;return i<55296||i>56319||n+1===r||(o=t.charCodeAt(n+1))<56320||o>57343?i:(i-55296<<10)+(o-56320)+65536}},wi=_i?function(t){return t.trimStart()}:function(t){return t.replace(fi,"")},Ci=gi?function(t){return t.trimEnd()}:function(t){return t.replace(hi,"")};function Pn(e,t){return new RegExp(e,t)}var mt$2;if(pt$2){var Gt$1=Pn("([^\\p{White_Space}\\p{Pattern_Syntax}]*)","yu");mt$2=function(t,n){var r;Gt$1.lastIndex=n;var i=Gt$1.exec(t);return (r=i[1])!==null&&r!==void 0?r:""};}else mt$2=function(t,n){for(var r=[];;){var i=Hn(t,n);if(i===void 0||Nn(i)||Bi(i))break;r.push(i),n+=i>=65536?2:1;}return dt$3.apply(void 0,r)};var Ei=function(){function e(t,n){n===void 0&&(n={}),this.message=t,this.position={offset:0,line:1,column:1},this.ignoreTag=!!n.ignoreTag,this.locale=n.locale,this.requiresOtherClause=!!n.requiresOtherClause,this.shouldParseSkeletons=!!n.shouldParseSkeletons;}return e.prototype.parse=function(){if(this.offset()!==0)throw Error("parser can only be used once");return this.parseMessage(0,"",!1)},e.prototype.parseMessage=function(t,n,r){for(var i=[];!this.isEOF();){var o=this.char();if(o===123){var s=this.parseArgument(t,r);if(s.err)return s;i.push(s.val);}else {if(o===125&&t>0)break;if(o===35&&(n==="plural"||n==="selectordinal")){var a=this.clonePosition();this.bump(),i.push({type:M.pound,location:S$1(a,this.clonePosition())});}else if(o===60&&!this.ignoreTag&&this.peek()===47){if(r)break;return this.error(x$2.UNMATCHED_CLOSING_TAG,S$1(this.clonePosition(),this.clonePosition()))}else if(o===60&&!this.ignoreTag&&At$2(this.peek()||0)){var s=this.parseTag(t,n);if(s.err)return s;i.push(s.val);}else {var s=this.parseLiteral(t,n);if(s.err)return s;i.push(s.val);}}}return {val:i,err:null}},e.prototype.parseTag=function(t,n){var r=this.clonePosition();this.bump();var i=this.parseTagName();if(this.bumpSpace(),this.bumpIf("/>"))return {val:{type:M.literal,value:"<".concat(i,"/>"),location:S$1(r,this.clonePosition())},err:null};if(this.bumpIf(">")){var o=this.parseMessage(t+1,n,!0);if(o.err)return o;var s=o.val,a=this.clonePosition();if(this.bumpIf("</")){if(this.isEOF()||!At$2(this.char()))return this.error(x$2.INVALID_TAG,S$1(a,this.clonePosition()));var u=this.clonePosition(),c=this.parseTagName();return i!==c?this.error(x$2.UNMATCHED_CLOSING_TAG,S$1(u,this.clonePosition())):(this.bumpSpace(),this.bumpIf(">")?{val:{type:M.tag,value:i,children:s,location:S$1(r,this.clonePosition())},err:null}:this.error(x$2.INVALID_TAG,S$1(a,this.clonePosition())))}else return this.error(x$2.UNCLOSED_TAG,S$1(r,this.clonePosition()))}else return this.error(x$2.INVALID_TAG,S$1(r,this.clonePosition()))},e.prototype.parseTagName=function(){var t=this.offset();for(this.bump();!this.isEOF()&&Si(this.char());)this.bump();return this.message.slice(t,this.offset())},e.prototype.parseLiteral=function(t,n){for(var r=this.clonePosition(),i="";;){var o=this.tryParseQuote(n);if(o){i+=o;continue}var s=this.tryParseUnquoted(t,n);if(s){i+=s;continue}var a=this.tryParseLeftAngleBracket();if(a){i+=a;continue}break}var u=S$1(r,this.clonePosition());return {val:{type:M.literal,value:i,location:u},err:null}},e.prototype.tryParseLeftAngleBracket=function(){return !this.isEOF()&&this.char()===60&&(this.ignoreTag||!xi(this.peek()||0))?(this.bump(),"<"):null},e.prototype.tryParseQuote=function(t){if(this.isEOF()||this.char()!==39)return null;switch(this.peek()){case 39:return this.bump(),this.bump(),"'";case 123:case 60:case 62:case 125:break;case 35:if(t==="plural"||t==="selectordinal")break;return null;default:return null}this.bump();var n=[this.char()];for(this.bump();!this.isEOF();){var r=this.char();if(r===39)if(this.peek()===39)n.push(39),this.bump();else {this.bump();break}else n.push(r);this.bump();}return dt$3.apply(void 0,n)},e.prototype.tryParseUnquoted=function(t,n){if(this.isEOF())return null;var r=this.char();return r===60||r===123||r===35&&(n==="plural"||n==="selectordinal")||r===125&&t>0?null:(this.bump(),dt$3(r))},e.prototype.parseArgument=function(t,n){var r=this.clonePosition();if(this.bump(),this.bumpSpace(),this.isEOF())return this.error(x$2.EXPECT_ARGUMENT_CLOSING_BRACE,S$1(r,this.clonePosition()));if(this.char()===125)return this.bump(),this.error(x$2.EMPTY_ARGUMENT,S$1(r,this.clonePosition()));var i=this.parseIdentifierIfPossible().value;if(!i)return this.error(x$2.MALFORMED_ARGUMENT,S$1(r,this.clonePosition()));if(this.bumpSpace(),this.isEOF())return this.error(x$2.EXPECT_ARGUMENT_CLOSING_BRACE,S$1(r,this.clonePosition()));switch(this.char()){case 125:return this.bump(),{val:{type:M.argument,value:i,location:S$1(r,this.clonePosition())},err:null};case 44:return this.bump(),this.bumpSpace(),this.isEOF()?this.error(x$2.EXPECT_ARGUMENT_CLOSING_BRACE,S$1(r,this.clonePosition())):this.parseArgumentOptions(t,n,i,r);default:return this.error(x$2.MALFORMED_ARGUMENT,S$1(r,this.clonePosition()))}},e.prototype.parseIdentifierIfPossible=function(){var t=this.clonePosition(),n=this.offset(),r=mt$2(this.message,n),i=n+r.length;this.bumpTo(i);var o=this.clonePosition(),s=S$1(t,o);return {value:r,location:s}},e.prototype.parseArgumentOptions=function(t,n,r,i){var o,s=this.clonePosition(),a=this.parseIdentifierIfPossible().value,u=this.clonePosition();switch(a){case"":return this.error(x$2.EXPECT_ARGUMENT_TYPE,S$1(s,u));case"number":case"date":case"time":{this.bumpSpace();var c=null;if(this.bumpIf(",")){this.bumpSpace();var l=this.clonePosition(),f=this.parseSimpleArgStyleIfPossible();if(f.err)return f;var h=Ci(f.val);if(h.length===0)return this.error(x$2.EXPECT_ARGUMENT_STYLE,S$1(this.clonePosition(),this.clonePosition()));var _=S$1(l,this.clonePosition());c={style:h,styleLocation:_};}var m=this.tryParseArgumentClose(i);if(m.err)return m;var B=S$1(i,this.clonePosition());if(c&&Ut$1(c?.style,"::",0)){var C=wi(c.style.slice(2));if(a==="number"){var f=this.parseNumberSkeletonFromString(C,c.styleLocation);return f.err?f:{val:{type:M.number,value:r,location:B,style:f.val},err:null}}else {if(C.length===0)return this.error(x$2.EXPECT_DATE_TIME_SKELETON,B);var k=C;this.locale&&(k=ci(C,this.locale));var h={type:we$2.dateTime,pattern:k,location:c.styleLocation,parsedOptions:this.shouldParseSkeletons?ni(k):{}},L=a==="date"?M.date:M.time;return {val:{type:L,value:r,location:B,style:h},err:null}}}return {val:{type:a==="number"?M.number:a==="date"?M.date:M.time,value:r,location:B,style:(o=c?.style)!==null&&o!==void 0?o:null},err:null}}case"plural":case"selectordinal":case"select":{var N=this.clonePosition();if(this.bumpSpace(),!this.bumpIf(","))return this.error(x$2.EXPECT_SELECT_ARGUMENT_OPTIONS,S$1(N,I({},N)));this.bumpSpace();var D=this.parseIdentifierIfPossible(),j=0;if(a!=="select"&&D.value==="offset"){if(!this.bumpIf(":"))return this.error(x$2.EXPECT_PLURAL_ARGUMENT_OFFSET_VALUE,S$1(this.clonePosition(),this.clonePosition()));this.bumpSpace();var f=this.tryParseDecimalInteger(x$2.EXPECT_PLURAL_ARGUMENT_OFFSET_VALUE,x$2.INVALID_PLURAL_ARGUMENT_OFFSET_VALUE);if(f.err)return f;this.bumpSpace(),D=this.parseIdentifierIfPossible(),j=f.val;}var P=this.tryParsePluralOrSelectOptions(t,a,n,D);if(P.err)return P;var m=this.tryParseArgumentClose(i);if(m.err)return m;var R=S$1(i,this.clonePosition());return a==="select"?{val:{type:M.select,value:r,options:jt$1(P.val),location:R},err:null}:{val:{type:M.plural,value:r,options:jt$1(P.val),offset:j,pluralType:a==="plural"?"cardinal":"ordinal",location:R},err:null}}default:return this.error(x$2.INVALID_ARGUMENT_TYPE,S$1(s,u))}},e.prototype.tryParseArgumentClose=function(t){return this.isEOF()||this.char()!==125?this.error(x$2.EXPECT_ARGUMENT_CLOSING_BRACE,S$1(t,this.clonePosition())):(this.bump(),{val:!0,err:null})},e.prototype.parseSimpleArgStyleIfPossible=function(){for(var t=0,n=this.clonePosition();!this.isEOF();){var r=this.char();switch(r){case 39:{this.bump();var i=this.clonePosition();if(!this.bumpUntil("'"))return this.error(x$2.UNCLOSED_QUOTE_IN_ARGUMENT_STYLE,S$1(i,this.clonePosition()));this.bump();break}case 123:{t+=1,this.bump();break}case 125:{if(t>0)t-=1;else return {val:this.message.slice(n.offset,this.offset()),err:null};break}default:this.bump();break}}return {val:this.message.slice(n.offset,this.offset()),err:null}},e.prototype.parseNumberSkeletonFromString=function(t,n){var r=[];try{r=ii(t);}catch{return this.error(x$2.INVALID_NUMBER_SKELETON,n)}return {val:{type:we$2.number,tokens:r,location:n,parsedOptions:this.shouldParseSkeletons?li(r):{}},err:null}},e.prototype.tryParsePluralOrSelectOptions=function(t,n,r,i){for(var o,s=!1,a=[],u=new Set,c=i.value,l=i.location;;){if(c.length===0){var f=this.clonePosition();if(n!=="select"&&this.bumpIf("=")){var h=this.tryParseDecimalInteger(x$2.EXPECT_PLURAL_ARGUMENT_SELECTOR,x$2.INVALID_PLURAL_ARGUMENT_SELECTOR);if(h.err)return h;l=S$1(f,this.clonePosition()),c=this.message.slice(f.offset,this.offset());}else break}if(u.has(c))return this.error(n==="select"?x$2.DUPLICATE_SELECT_ARGUMENT_SELECTOR:x$2.DUPLICATE_PLURAL_ARGUMENT_SELECTOR,l);c==="other"&&(s=!0),this.bumpSpace();var _=this.clonePosition();if(!this.bumpIf("{"))return this.error(n==="select"?x$2.EXPECT_SELECT_ARGUMENT_SELECTOR_FRAGMENT:x$2.EXPECT_PLURAL_ARGUMENT_SELECTOR_FRAGMENT,S$1(this.clonePosition(),this.clonePosition()));var m=this.parseMessage(t+1,n,r);if(m.err)return m;var B=this.tryParseArgumentClose(_);if(B.err)return B;a.push([c,{value:m.val,location:S$1(_,this.clonePosition())}]),u.add(c),this.bumpSpace(),o=this.parseIdentifierIfPossible(),c=o.value,l=o.location;}return a.length===0?this.error(n==="select"?x$2.EXPECT_SELECT_ARGUMENT_SELECTOR:x$2.EXPECT_PLURAL_ARGUMENT_SELECTOR,S$1(this.clonePosition(),this.clonePosition())):this.requiresOtherClause&&!s?this.error(x$2.MISSING_OTHER_CLAUSE,S$1(this.clonePosition(),this.clonePosition())):{val:a,err:null}},e.prototype.tryParseDecimalInteger=function(t,n){var r=1,i=this.clonePosition();this.bumpIf("+")||this.bumpIf("-")&&(r=-1);for(var o=!1,s=0;!this.isEOF();){var a=this.char();if(a>=48&&a<=57)o=!0,s=s*10+(a-48),this.bump();else break}var u=S$1(i,this.clonePosition());return o?(s*=r,vi(s)?{val:s,err:null}:this.error(n,u)):this.error(t,u)},e.prototype.offset=function(){return this.position.offset},e.prototype.isEOF=function(){return this.offset()===this.message.length},e.prototype.clonePosition=function(){return {offset:this.position.offset,line:this.position.line,column:this.position.column}},e.prototype.char=function(){var t=this.position.offset;if(t>=this.message.length)throw Error("out of bound");var n=Hn(this.message,t);if(n===void 0)throw Error("Offset ".concat(t," is at invalid UTF-16 code unit boundary"));return n},e.prototype.error=function(t,n){return {val:null,err:{kind:t,message:this.message,location:n}}},e.prototype.bump=function(){if(!this.isEOF()){var t=this.char();t===10?(this.position.line+=1,this.position.column=1,this.position.offset+=1):(this.position.column+=1,this.position.offset+=t<65536?1:2);}},e.prototype.bumpIf=function(t){if(Ut$1(this.message,t,this.offset())){for(var n=0;n<t.length;n++)this.bump();return !0}return !1},e.prototype.bumpUntil=function(t){var n=this.offset(),r=this.message.indexOf(t,n);return r>=0?(this.bumpTo(r),!0):(this.bumpTo(this.message.length),!1)},e.prototype.bumpTo=function(t){if(this.offset()>t)throw Error("targetOffset ".concat(t," must be greater than or equal to the current offset ").concat(this.offset()));for(t=Math.min(t,this.message.length);;){var n=this.offset();if(n===t)break;if(n>t)throw Error("targetOffset ".concat(t," is at invalid UTF-16 code unit boundary"));if(this.bump(),this.isEOF())break}},e.prototype.bumpSpace=function(){for(;!this.isEOF()&&Nn(this.char());)this.bump();},e.prototype.peek=function(){if(this.isEOF())return null;var t=this.char(),n=this.offset(),r=this.message.charCodeAt(n+(t>=65536?2:1));return r??null},e}();function At$2(e){return e>=97&&e<=122||e>=65&&e<=90}function xi(e){return At$2(e)||e===47}function Si(e){return e===45||e===46||e>=48&&e<=57||e===95||e>=97&&e<=122||e>=65&&e<=90||e==183||e>=192&&e<=214||e>=216&&e<=246||e>=248&&e<=893||e>=895&&e<=8191||e>=8204&&e<=8205||e>=8255&&e<=8256||e>=8304&&e<=8591||e>=11264&&e<=12271||e>=12289&&e<=55295||e>=63744&&e<=64975||e>=65008&&e<=65533||e>=65536&&e<=983039}function Nn(e){return e>=9&&e<=13||e===32||e===133||e>=8206&&e<=8207||e===8232||e===8233}function Bi(e){return e>=33&&e<=35||e===36||e>=37&&e<=39||e===40||e===41||e===42||e===43||e===44||e===45||e>=46&&e<=47||e>=58&&e<=59||e>=60&&e<=62||e>=63&&e<=64||e===91||e===92||e===93||e===94||e===96||e===123||e===124||e===125||e===126||e===161||e>=162&&e<=165||e===166||e===167||e===169||e===171||e===172||e===174||e===176||e===177||e===182||e===187||e===191||e===215||e===247||e>=8208&&e<=8213||e>=8214&&e<=8215||e===8216||e===8217||e===8218||e>=8219&&e<=8220||e===8221||e===8222||e===8223||e>=8224&&e<=8231||e>=8240&&e<=8248||e===8249||e===8250||e>=8251&&e<=8254||e>=8257&&e<=8259||e===8260||e===8261||e===8262||e>=8263&&e<=8273||e===8274||e===8275||e>=8277&&e<=8286||e>=8592&&e<=8596||e>=8597&&e<=8601||e>=8602&&e<=8603||e>=8604&&e<=8607||e===8608||e>=8609&&e<=8610||e===8611||e>=8612&&e<=8613||e===8614||e>=8615&&e<=8621||e===8622||e>=8623&&e<=8653||e>=8654&&e<=8655||e>=8656&&e<=8657||e===8658||e===8659||e===8660||e>=8661&&e<=8691||e>=8692&&e<=8959||e>=8960&&e<=8967||e===8968||e===8969||e===8970||e===8971||e>=8972&&e<=8991||e>=8992&&e<=8993||e>=8994&&e<=9e3||e===9001||e===9002||e>=9003&&e<=9083||e===9084||e>=9085&&e<=9114||e>=9115&&e<=9139||e>=9140&&e<=9179||e>=9180&&e<=9185||e>=9186&&e<=9254||e>=9255&&e<=9279||e>=9280&&e<=9290||e>=9291&&e<=9311||e>=9472&&e<=9654||e===9655||e>=9656&&e<=9664||e===9665||e>=9666&&e<=9719||e>=9720&&e<=9727||e>=9728&&e<=9838||e===9839||e>=9840&&e<=10087||e===10088||e===10089||e===10090||e===10091||e===10092||e===10093||e===10094||e===10095||e===10096||e===10097||e===10098||e===10099||e===10100||e===10101||e>=10132&&e<=10175||e>=10176&&e<=10180||e===10181||e===10182||e>=10183&&e<=10213||e===10214||e===10215||e===10216||e===10217||e===10218||e===10219||e===10220||e===10221||e===10222||e===10223||e>=10224&&e<=10239||e>=10240&&e<=10495||e>=10496&&e<=10626||e===10627||e===10628||e===10629||e===10630||e===10631||e===10632||e===10633||e===10634||e===10635||e===10636||e===10637||e===10638||e===10639||e===10640||e===10641||e===10642||e===10643||e===10644||e===10645||e===10646||e===10647||e===10648||e>=10649&&e<=10711||e===10712||e===10713||e===10714||e===10715||e>=10716&&e<=10747||e===10748||e===10749||e>=10750&&e<=11007||e>=11008&&e<=11055||e>=11056&&e<=11076||e>=11077&&e<=11078||e>=11079&&e<=11084||e>=11085&&e<=11123||e>=11124&&e<=11125||e>=11126&&e<=11157||e===11158||e>=11159&&e<=11263||e>=11776&&e<=11777||e===11778||e===11779||e===11780||e===11781||e>=11782&&e<=11784||e===11785||e===11786||e===11787||e===11788||e===11789||e>=11790&&e<=11798||e===11799||e>=11800&&e<=11801||e===11802||e===11803||e===11804||e===11805||e>=11806&&e<=11807||e===11808||e===11809||e===11810||e===11811||e===11812||e===11813||e===11814||e===11815||e===11816||e===11817||e>=11818&&e<=11822||e===11823||e>=11824&&e<=11833||e>=11834&&e<=11835||e>=11836&&e<=11839||e===11840||e===11841||e===11842||e>=11843&&e<=11855||e>=11856&&e<=11857||e===11858||e>=11859&&e<=11903||e>=12289&&e<=12291||e===12296||e===12297||e===12298||e===12299||e===12300||e===12301||e===12302||e===12303||e===12304||e===12305||e>=12306&&e<=12307||e===12308||e===12309||e===12310||e===12311||e===12312||e===12313||e===12314||e===12315||e===12316||e===12317||e>=12318&&e<=12319||e===12320||e===12336||e===64830||e===64831||e>=65093&&e<=65094}function _t$2(e){e.forEach(function(t){if(delete t.location,Cn(t)||En(t))for(var n in t.options)delete t.options[n].location,_t$2(t.options[n].value);else vn(t)&&Sn(t.style)||(yn(t)||wn(t))&&ht$1(t.style)?delete t.style.location:xn(t)&&_t$2(t.children);});}function Ii(e,t){t===void 0&&(t={}),t=I({shouldParseSkeletons:!0,requiresOtherClause:!0},t);var n=new Ei(e,t).parse();if(n.err){var r=SyntaxError(x$2[n.err.kind]);throw r.location=n.err.location,r.originalMessage=n.err.message,r}return t?.captureLocation||_t$2(n.val),n.val}var Ce$2;(function(e){e.MISSING_VALUE="MISSING_VALUE",e.INVALID_VALUE="INVALID_VALUE",e.MISSING_INTL_API="MISSING_INTL_API";})(Ce$2||(Ce$2={}));var qe$2=function(e){Ve$1(t,e);function t(n,r,i){var o=e.call(this,n)||this;return o.code=r,o.originalMessage=i,o}return t.prototype.toString=function(){return "[formatjs Error: ".concat(this.code,"] ").concat(this.message)},t}(Error),Ft$1=function(e){Ve$1(t,e);function t(n,r,i,o){return e.call(this,'Invalid values for "'.concat(n,'": "').concat(r,'". Options are "').concat(Object.keys(i).join('", "'),'"'),Ce$2.INVALID_VALUE,o)||this}return t}(qe$2),Ti=function(e){Ve$1(t,e);function t(n,r,i){return e.call(this,'Value for "'.concat(n,'" must be of type ').concat(r),Ce$2.INVALID_VALUE,i)||this}return t}(qe$2),Oi=function(e){Ve$1(t,e);function t(n,r){return e.call(this,'The intl string context variable "'.concat(n,'" was not provided to the string "').concat(r,'"'),Ce$2.MISSING_VALUE,r)||this}return t}(qe$2),$$1;(function(e){e[e.literal=0]="literal",e[e.object=1]="object";})($$1||($$1={}));function Hi(e){return e.length<2?e:e.reduce(function(t,n){var r=t[t.length-1];return !r||r.type!==$$1.literal||n.type!==$$1.literal?t.push(n):r.value+=n.value,t},[])}function Pi(e){return typeof e=="function"}function je$1(e,t,n,r,i,o,s){if(e.length===1&&Lt$2(e[0]))return [{type:$$1.literal,value:e[0].value}];for(var a=[],u=0,c=e;u<c.length;u++){var l=c[u];if(Lt$2(l)){a.push({type:$$1.literal,value:l.value});continue}if(ei(l)){typeof o=="number"&&a.push({type:$$1.literal,value:n.getNumberFormat(t).format(o)});continue}var f=l.value;if(!(i&&f in i))throw new Oi(f,s);var h=i[f];if(Jr$1(l)){(!h||typeof h=="string"||typeof h=="number")&&(h=typeof h=="string"||typeof h=="number"?String(h):""),a.push({type:typeof h=="string"?$$1.literal:$$1.object,value:h});continue}if(yn(l)){var _=typeof l.style=="string"?r.date[l.style]:ht$1(l.style)?l.style.parsedOptions:void 0;a.push({type:$$1.literal,value:n.getDateTimeFormat(t,_).format(h)});continue}if(wn(l)){var _=typeof l.style=="string"?r.time[l.style]:ht$1(l.style)?l.style.parsedOptions:r.time.medium;a.push({type:$$1.literal,value:n.getDateTimeFormat(t,_).format(h)});continue}if(vn(l)){var _=typeof l.style=="string"?r.number[l.style]:Sn(l.style)?l.style.parsedOptions:void 0;_&&_.scale&&(h=h*(_.scale||1)),a.push({type:$$1.literal,value:n.getNumberFormat(t,_).format(h)});continue}if(xn(l)){var m=l.children,B=l.value,C=i[B];if(!Pi(C))throw new Ti(B,"function",s);var k=je$1(m,t,n,r,i,o),L=C(k.map(function(j){return j.value}));Array.isArray(L)||(L=[L]),a.push.apply(a,L.map(function(j){return {type:typeof j=="string"?$$1.literal:$$1.object,value:j}}));}if(Cn(l)){var N=l.options[h]||l.options.other;if(!N)throw new Ft$1(l.value,h,Object.keys(l.options),s);a.push.apply(a,je$1(N.value,t,n,r,i));continue}if(En(l)){var N=l.options["=".concat(h)];if(!N){if(!Intl.PluralRules)throw new qe$2(`Intl.PluralRules is not available in this environment.
Try polyfilling it using "@formatjs/intl-pluralrules"
`,Ce$2.MISSING_INTL_API,s);var D=n.getPluralRules(t,{type:l.pluralType}).select(h-(l.offset||0));N=l.options[D]||l.options.other;}if(!N)throw new Ft$1(l.value,h,Object.keys(l.options),s);a.push.apply(a,je$1(N.value,t,n,r,i,h-(l.offset||0)));continue}}return Hi(a)}function Ni(e,t){return t?I(I(I({},e||{}),t||{}),Object.keys(e).reduce(function(n,r){return n[r]=I(I({},e[r]),t[r]||{}),n},{})):e}function Mi(e,t){return t?Object.keys(e).reduce(function(n,r){return n[r]=Ni(e[r],t[r]),n},I({},e)):e}function it$4(e){return {create:function(){return {get:function(t){return e[t]},set:function(t,n){e[t]=n;}}}}}function Li(e){return e===void 0&&(e={number:{},dateTime:{},pluralRules:{}}),{getNumberFormat:tt$2(function(){for(var t,n=[],r=0;r<arguments.length;r++)n[r]=arguments[r];return new((t=Intl.NumberFormat).bind.apply(t,et$3([void 0],n,!1)))},{cache:it$4(e.number),strategy:nt$3.variadic}),getDateTimeFormat:tt$2(function(){for(var t,n=[],r=0;r<arguments.length;r++)n[r]=arguments[r];return new((t=Intl.DateTimeFormat).bind.apply(t,et$3([void 0],n,!1)))},{cache:it$4(e.dateTime),strategy:nt$3.variadic}),getPluralRules:tt$2(function(){for(var t,n=[],r=0;r<arguments.length;r++)n[r]=arguments[r];return new((t=Intl.PluralRules).bind.apply(t,et$3([void 0],n,!1)))},{cache:it$4(e.pluralRules),strategy:nt$3.variadic})}}var Mn=function(){function e(t,n,r,i){n===void 0&&(n=e.defaultLocale);var o=this;if(this.formatterCache={number:{},dateTime:{},pluralRules:{}},this.format=function(u){var c=o.formatToParts(u);if(c.length===1)return c[0].value;var l=c.reduce(function(f,h){return !f.length||h.type!==$$1.literal||typeof f[f.length-1]!="string"?f.push(h.value):f[f.length-1]+=h.value,f},[]);return l.length<=1?l[0]||"":l},this.formatToParts=function(u){return je$1(o.ast,o.locales,o.formatters,o.formats,u,void 0,o.message)},this.resolvedOptions=function(){var u;return {locale:((u=o.resolvedLocale)===null||u===void 0?void 0:u.toString())||Intl.NumberFormat.supportedLocalesOf(o.locales)[0]}},this.getAst=function(){return o.ast},this.locales=n,this.resolvedLocale=e.resolveLocale(n),typeof t=="string"){if(this.message=t,!e.__parse)throw new TypeError("IntlMessageFormat.__parse must be set to process `message` of type `string`");var s=i||{};s.formatters;var a=Wr$1(s,["formatters"]);this.ast=e.__parse(t,I(I({},a),{locale:this.resolvedLocale}));}else this.ast=t;if(!Array.isArray(this.ast))throw new TypeError("A message must be provided as a String or AST.");this.formats=Mi(e.formats,r),this.formatters=i&&i.formatters||Li(this.formatterCache);}return Object.defineProperty(e,"defaultLocale",{get:function(){return e.memoizedDefaultLocale||(e.memoizedDefaultLocale=new Intl.NumberFormat().resolvedOptions().locale),e.memoizedDefaultLocale},enumerable:!1,configurable:!0}),e.memoizedDefaultLocale=null,e.resolveLocale=function(t){if(!(typeof Intl.Locale>"u")){var n=Intl.NumberFormat.supportedLocalesOf(t);return n.length>0?new Intl.Locale(n[0]):new Intl.Locale(typeof t=="string"?t:t[0])}},e.__parse=Ii,e.formats={number:{integer:{maximumFractionDigits:0},currency:{style:"currency"},percent:{style:"percent"}},date:{short:{month:"numeric",day:"numeric",year:"2-digit"},medium:{month:"short",day:"numeric",year:"numeric"},long:{month:"long",day:"numeric",year:"numeric"},full:{weekday:"long",month:"long",day:"numeric",year:"numeric"}},time:{short:{hour:"numeric",minute:"numeric"},medium:{hour:"numeric",minute:"numeric",second:"numeric"},long:{hour:"numeric",minute:"numeric",second:"numeric",timeZoneName:"short"},full:{hour:"numeric",minute:"numeric",second:"numeric",timeZoneName:"short"}}},e}();function Ri(e,t){if(t==null)return;if(t in e)return e[t];const n=t.split(".");let r=e;for(let i=0;i<n.length;i++)if(typeof r=="object"){if(i>0){const o=n.slice(i,n.length).join(".");if(o in r){r=r[o];break}}r=r[n[i]];}else r=void 0;return r}const ue$1={},ki=(e,t,n)=>n&&(t in ue$1||(ue$1[t]={}),e in ue$1[t]||(ue$1[t][e]=n),n),Ln=(e,t)=>{if(t==null)return;if(t in ue$1&&e in ue$1[t])return ue$1[t][e];const n=ke$1(t);for(let r=0;r<n.length;r++){const i=n[r],o=Ui(i,e);if(o)return ki(e,t,o)}};let wt$1;const xe$2=writable({});function Di(e){return wt$1[e]||null}function Ct$3(e){return e in wt$1}function Ui(e,t){if(!Ct$3(e))return null;const n=Di(e);return Ri(n,t)}function ji(e){if(e==null)return;const t=ke$1(e);for(let n=0;n<t.length;n++){const r=t[n];if(Ct$3(r))return r}}function Ge$1(e,...t){delete ue$1[e],xe$2.update(n=>(n[e]=$r$1.all([n[e]||{},...t]),n));}derived([xe$2],([e])=>Object.keys(e));xe$2.subscribe(e=>wt$1=e);const He$1={};function Gi(e){He$1[e]=new Set;}function Fi(e,t){He$1[e].delete(t),He$1[e].size===0&&delete He$1[e];}function Pe$1(e){return He$1[e]}function zi(e){return ke$1(e).map(t=>{const n=Pe$1(t);return [t,n?[...n]:[]]}).filter(([,t])=>t.length>0)}function Fe$1(e){return e==null?!1:ke$1(e).some(t=>{var n;return (n=Pe$1(t))==null?void 0:n.size})}function $i(e,t){return Promise.all(t.map(r=>(Fi(e,r),r().then(i=>i.default||i)))).then(r=>Ge$1(e,...r))}const Ie$1={};function Rn(e){if(!Fe$1(e))return e in Ie$1?Ie$1[e]:Promise.resolve();const t=zi(e);return Ie$1[e]=Promise.all(t.map(([n,r])=>$i(n,r))).then(()=>{if(Fe$1(e))return Rn(e);delete Ie$1[e];}),Ie$1[e]}function Wi(e,t){Pe$1(e)||Gi(e);const n=Pe$1(e);Pe$1(e).has(t)||(Ct$3(e)||xe$2.update(r=>(r[e]={},r)),n.add(t));}var zt$1=Object.getOwnPropertySymbols,Vi=Object.prototype.hasOwnProperty,qi=Object.prototype.propertyIsEnumerable,Qi=(e,t)=>{var n={};for(var r in e)Vi.call(e,r)&&t.indexOf(r)<0&&(n[r]=e[r]);if(e!=null&&zt$1)for(var r of zt$1(e))t.indexOf(r)<0&&qi.call(e,r)&&(n[r]=e[r]);return n};const Xi={number:{scientific:{notation:"scientific"},engineering:{notation:"engineering"},compactLong:{notation:"compact",compactDisplay:"long"},compactShort:{notation:"compact",compactDisplay:"short"}},date:{short:{month:"numeric",day:"numeric",year:"2-digit"},medium:{month:"short",day:"numeric",year:"numeric"},long:{month:"long",day:"numeric",year:"numeric"},full:{weekday:"long",month:"long",day:"numeric",year:"numeric"}},time:{short:{hour:"numeric",minute:"numeric"},medium:{hour:"numeric",minute:"numeric",second:"numeric"},long:{hour:"numeric",minute:"numeric",second:"numeric",timeZoneName:"short"},full:{hour:"numeric",minute:"numeric",second:"numeric",timeZoneName:"short"}}};function Ki({locale:e,id:t}){console.warn(`[svelte-i18n] The message "${t}" was not found in "${ke$1(e).join('", "')}".${Fe$1(fe$2())?`

Note: there are at least one loader still registered to this locale that wasn't executed.`:""}`);}const Zi={fallbackLocale:null,loadingDelay:200,formats:Xi,warnOnMissingMessages:!0,handleMissingMessage:void 0,ignoreTag:!0},Oe$1=Zi;function Ee$1(){return Oe$1}function Yi(e){const t=e,{formats:n}=t,r=Qi(t,["formats"]);let i=e.fallbackLocale;if(e.initialLocale)try{Mn.resolveLocale(e.initialLocale)&&(i=e.initialLocale);}catch{console.warn(`[svelte-i18n] The initial locale "${e.initialLocale}" is not a valid locale.`);}return r.warnOnMissingMessages&&(delete r.warnOnMissingMessages,r.handleMissingMessage==null?r.handleMissingMessage=Ki:console.warn('[svelte-i18n] The "warnOnMissingMessages" option is deprecated. Please use the "handleMissingMessage" option instead.')),Object.assign(Oe$1,r,{initialLocale:i}),n&&("number"in n&&Object.assign(Oe$1.formats.number,n.number),"date"in n&&Object.assign(Oe$1.formats.date,n.date),"time"in n&&Object.assign(Oe$1.formats.time,n.time)),_e$1.set(i)}const ot$3=writable(!1);var Ji=Object.defineProperty,eo=Object.defineProperties,to=Object.getOwnPropertyDescriptors,$t$1=Object.getOwnPropertySymbols,no=Object.prototype.hasOwnProperty,ro=Object.prototype.propertyIsEnumerable,Wt$2=(e,t,n)=>t in e?Ji(e,t,{enumerable:!0,configurable:!0,writable:!0,value:n}):e[t]=n,io=(e,t)=>{for(var n in t||(t={}))no.call(t,n)&&Wt$2(e,n,t[n]);if($t$1)for(var n of $t$1(t))ro.call(t,n)&&Wt$2(e,n,t[n]);return e},oo=(e,t)=>eo(e,to(t));let gt$1;const ze$2=writable(null);function Vt$1(e){return e.split("-").map((t,n,r)=>r.slice(0,n+1).join("-")).reverse()}function ke$1(e,t=Ee$1().fallbackLocale){const n=Vt$1(e);return t?[...new Set([...n,...Vt$1(t)])]:n}function fe$2(){return gt$1??void 0}ze$2.subscribe(e=>{gt$1=e??void 0,typeof window<"u"&&e!=null&&document.documentElement.setAttribute("lang",e);});const so=e=>{if(e&&ji(e)&&Fe$1(e)){const{loadingDelay:t}=Ee$1();let n;return typeof window<"u"&&fe$2()!=null&&t?n=window.setTimeout(()=>ot$3.set(!0),t):ot$3.set(!0),Rn(e).then(()=>{ze$2.set(e);}).finally(()=>{clearTimeout(n),ot$3.set(!1);})}return ze$2.set(e)},_e$1=oo(io({},ze$2),{set:so}),ao=()=>typeof window>"u"?null:window.navigator.language||window.navigator.languages[0],Qe$1=e=>{const t=Object.create(null);return r=>{const i=JSON.stringify(r);return i in t?t[i]:t[i]=e(r)}};var lo=Object.defineProperty,$e$1=Object.getOwnPropertySymbols,kn=Object.prototype.hasOwnProperty,Dn=Object.prototype.propertyIsEnumerable,qt$2=(e,t,n)=>t in e?lo(e,t,{enumerable:!0,configurable:!0,writable:!0,value:n}):e[t]=n,Et$2=(e,t)=>{for(var n in t||(t={}))kn.call(t,n)&&qt$2(e,n,t[n]);if($e$1)for(var n of $e$1(t))Dn.call(t,n)&&qt$2(e,n,t[n]);return e},Se$1=(e,t)=>{var n={};for(var r in e)kn.call(e,r)&&t.indexOf(r)<0&&(n[r]=e[r]);if(e!=null&&$e$1)for(var r of $e$1(e))t.indexOf(r)<0&&Dn.call(e,r)&&(n[r]=e[r]);return n};const Re$1=(e,t)=>{const{formats:n}=Ee$1();if(e in n&&t in n[e])return n[e][t];throw new Error(`[svelte-i18n] Unknown "${t}" ${e} format.`)},co=Qe$1(e=>{var t=e,{locale:n,format:r}=t,i=Se$1(t,["locale","format"]);if(n==null)throw new Error('[svelte-i18n] A "locale" must be set to format numbers');return r&&(i=Re$1("number",r)),new Intl.NumberFormat(n,i)}),uo=Qe$1(e=>{var t=e,{locale:n,format:r}=t,i=Se$1(t,["locale","format"]);if(n==null)throw new Error('[svelte-i18n] A "locale" must be set to format dates');return r?i=Re$1("date",r):Object.keys(i).length===0&&(i=Re$1("date","short")),new Intl.DateTimeFormat(n,i)}),fo=Qe$1(e=>{var t=e,{locale:n,format:r}=t,i=Se$1(t,["locale","format"]);if(n==null)throw new Error('[svelte-i18n] A "locale" must be set to format time values');return r?i=Re$1("time",r):Object.keys(i).length===0&&(i=Re$1("time","short")),new Intl.DateTimeFormat(n,i)}),ho=(e={})=>{var t=e,{locale:n=fe$2()}=t,r=Se$1(t,["locale"]);return co(Et$2({locale:n},r))},po=(e={})=>{var t=e,{locale:n=fe$2()}=t,r=Se$1(t,["locale"]);return uo(Et$2({locale:n},r))},mo=(e={})=>{var t=e,{locale:n=fe$2()}=t,r=Se$1(t,["locale"]);return fo(Et$2({locale:n},r))},Ao=Qe$1((e,t=fe$2())=>new Mn(e,t,Ee$1().formats,{ignoreTag:Ee$1().ignoreTag})),_o=(e,t={})=>{var n,r,i,o;let s=t;typeof e=="object"&&(s=e,e=s.id);const{values:a,locale:u=fe$2(),default:c}=s;if(u==null)throw new Error("[svelte-i18n] Cannot format a message without first setting the initial locale.");let l=Ln(e,u);if(!l)l=(o=(i=(r=(n=Ee$1()).handleMissingMessage)==null?void 0:r.call(n,{locale:u,id:e,defaultValue:c}))!=null?i:c)!=null?o:e;else if(typeof l!="string")return console.warn(`[svelte-i18n] Message with id "${e}" must be of type "string", found: "${typeof l}". Gettin its value through the "$format" method is deprecated; use the "json" method instead.`),l;if(!a)return l;let f=l;try{f=Ao(l,u).format(a);}catch(h){h instanceof Error&&console.warn(`[svelte-i18n] Message "${e}" has syntax error:`,h.message);}return f},go=(e,t)=>mo(t).format(e),bo=(e,t)=>po(t).format(e),vo=(e,t)=>ho(t).format(e),yo=(e,t=fe$2())=>Ln(e,t),xt$2=derived([_e$1,xe$2],()=>_o);derived([_e$1],()=>go);derived([_e$1],()=>bo);derived([_e$1],()=>vo);derived([_e$1,xe$2],()=>yo);const wo={code:".nav-holder.svelte-16faplo.svelte-16faplo{padding:var(--size-2) 0;border-bottom:solid 1px var(--border-color-primary)}nav.svelte-16faplo.svelte-16faplo{display:flex;flex-wrap:wrap;gap:var(--size-2);justify-content:flex-end;margin:0 auto;padding:0 var(--size-8)}nav.svelte-16faplo a.svelte-16faplo,button.svelte-16faplo.svelte-16faplo{padding:var(--size-1) var(--size-2);border-radius:var(--block-radius);border-width:var(--block-border-width);border-color:transparent;color:var(--body-text-color-subdued)}nav.svelte-16faplo a.active.svelte-16faplo,button.active.svelte-16faplo.svelte-16faplo{color:var(--body-text-color);border-color:var(--block-border-color);background-color:var(--block-background-fill)}.gradio-container-5-44-1.svelte-16faplo.svelte-16faplo{display:flex;position:relative;flex-direction:column;padding:0;min-height:1px;overflow:hidden;color:var(--button-secondary-text-color)}.embed-container.svelte-16faplo.svelte-16faplo{margin:var(--size-4) 0px;border:1px solid var(--button-secondary-border-color);border-radius:var(--embed-radius)}.with-info.svelte-16faplo.svelte-16faplo{padding-bottom:var(--size-7)}.embed-container.svelte-16faplo>main.svelte-16faplo{padding:var(--size-4)}main.svelte-16faplo.svelte-16faplo{display:flex;flex-grow:1;flex-direction:column}.app.svelte-16faplo.svelte-16faplo{position:relative;margin:auto;padding:var(--size-4) var(--size-8);width:100%;height:100%}@media(min-width: 640px){.fillable.svelte-16faplo.svelte-16faplo:not(.fill_width){max-width:640px}}@media(min-width: 768px){.fillable.svelte-16faplo.svelte-16faplo:not(.fill_width){max-width:768px}}@media(min-width: 1024px){.fillable.svelte-16faplo.svelte-16faplo:not(.fill_width){max-width:1024px}}@media(min-width: 1280px){.fillable.svelte-16faplo.svelte-16faplo:not(.fill_width){max-width:1280px}}@media(min-width: 1536px){.fillable.svelte-16faplo.svelte-16faplo:not(.fill_width){max-width:1536px}}@media(min-width: 1920px){.fillable.svelte-16faplo.svelte-16faplo:not(.fill_width){max-width:1920px}}.info.svelte-16faplo.svelte-16faplo{display:flex;position:absolute;bottom:0;justify-content:flex-start;border-top:1px solid var(--button-secondary-border-color);padding:var(--size-1) var(--size-5);width:100%;color:var(--body-text-color-subdued);font-size:var(--text-md);white-space:nowrap}.info.svelte-16faplo>span.svelte-16faplo{word-wrap:break-word;-break:keep-all;display:block;word-break:keep-all}.info.svelte-16faplo>span.svelte-16faplo:nth-child(1){margin-right:4px;min-width:0px;max-width:max-content;overflow:hidden;color:var(--body-text-color);text-overflow:ellipsis;white-space:nowrap}.info.svelte-16faplo>span.svelte-16faplo:nth-child(2){margin-right:3px}.info.svelte-16faplo>span.svelte-16faplo:nth-child(2),.info.svelte-16faplo>span.svelte-16faplo:nth-child(3){width:max-content}.info.svelte-16faplo>span.svelte-16faplo:nth-child(3){align-self:flex-end;justify-self:flex-end;margin-left:auto;text-align:right}.info.svelte-16faplo>span.svelte-16faplo:nth-child(1){flex-shrink:9}.hidden-title.svelte-16faplo.svelte-16faplo{position:absolute;left:var(--size-5);opacity:0;background:var(--button-secondary-background-fill);padding-right:4px}.info.svelte-16faplo a.svelte-16faplo{color:var(--body-text-color)}.title.svelte-16faplo.svelte-16faplo{font-size:var(--text-sm);font-family:var(--font-mono)}.hf.svelte-16faplo.svelte-16faplo{margin-left:5px}.space-logo.svelte-16faplo img.svelte-16faplo{display:inline-block;margin-bottom:4px;height:12px}main.svelte-16faplo a.svelte-16faplo:hover{text-decoration:underline}",map:'{"version":3,"file":"Embed.svelte","sources":["Embed.svelte"],"sourcesContent":["<script lang=\\"ts\\">import { getContext } from \\"svelte\\";\\nimport space_logo from \\"./images/spaces.svg\\";\\nimport { _ } from \\"svelte-i18n\\";\\nexport let wrapper;\\nexport let version;\\nexport let initial_height;\\nexport let fill_width;\\nexport let is_embed;\\nexport let is_lite;\\nexport let space;\\nexport let display;\\nexport let info;\\nexport let loaded;\\nexport let pages = [];\\nexport let current_page = \\"\\";\\nexport let root;\\nconst set_page = getContext(\\"set_lite_page\\");\\n<\/script>\\n\\n<div\\n\\tbind:this={wrapper}\\n\\tclass:fill_width\\n\\tclass:embed-container={display}\\n\\tclass:with-info={info}\\n\\tclass=\\"gradio-container gradio-container-{version}\\"\\n\\tstyle:min-height={loaded ? \\"initial\\" : initial_height}\\n\\tstyle:flex-grow={!display ? \\"1\\" : \\"auto\\"}\\n\\tdata-iframe-height\\n>\\n\\t{#if pages.length > 1}\\n\\t\\t<div class=\\"nav-holder\\">\\n\\t\\t\\t<nav class=\\"fillable\\" class:fill_width>\\n\\t\\t\\t\\t{#each pages as [route, label], i}\\n\\t\\t\\t\\t\\t{#if is_lite}\\n\\t\\t\\t\\t\\t\\t<button\\n\\t\\t\\t\\t\\t\\t\\tclass:active={route === current_page}\\n\\t\\t\\t\\t\\t\\t\\ton:click={(e) => {\\n\\t\\t\\t\\t\\t\\t\\t\\te.preventDefault();\\n\\t\\t\\t\\t\\t\\t\\t\\tset_page?.(route);\\n\\t\\t\\t\\t\\t\\t\\t}}\\n\\t\\t\\t\\t\\t\\t\\t>{label}\\n\\t\\t\\t\\t\\t\\t</button>\\n\\t\\t\\t\\t\\t{:else}\\n\\t\\t\\t\\t\\t\\t<a\\n\\t\\t\\t\\t\\t\\t\\thref={`${root}/${route}`}\\n\\t\\t\\t\\t\\t\\t\\tclass:active={route === current_page}\\n\\t\\t\\t\\t\\t\\t\\tdata-sveltekit-reload\\n\\t\\t\\t\\t\\t\\t\\t>{label}\\n\\t\\t\\t\\t\\t\\t</a>\\n\\t\\t\\t\\t\\t{/if}\\n\\t\\t\\t\\t{/each}\\n\\t\\t\\t</nav>\\n\\t\\t</div>\\n\\t{/if}\\n\\t<main class=\\"fillable\\" class:fill_width class:app={!display && !is_embed}>\\n\\t\\t<slot />\\n\\t\\t<div>\\n\\t\\t\\t{#if display && space && info}\\n\\t\\t\\t\\t<div class=\\"info\\">\\n\\t\\t\\t\\t\\t<span>\\n\\t\\t\\t\\t\\t\\t<a href=\\"https://huggingface.co/spaces/{space}\\" class=\\"title\\"\\n\\t\\t\\t\\t\\t\\t\\t>{space}</a\\n\\t\\t\\t\\t\\t\\t>\\n\\t\\t\\t\\t\\t</span>\\n\\t\\t\\t\\t\\t<span>\\n\\t\\t\\t\\t\\t\\t{$_(\\"common.built_with\\")}\\n\\t\\t\\t\\t\\t\\t<a class=\\"gradio\\" href=\\"https://gradio.app\\">Gradio</a>.\\n\\t\\t\\t\\t\\t</span>\\n\\t\\t\\t\\t\\t<span>\\n\\t\\t\\t\\t\\t\\t{$_(\\"common.hosted_on\\")}\\n\\t\\t\\t\\t\\t\\t<a class=\\"hf\\" href=\\"https://huggingface.co/spaces\\"\\n\\t\\t\\t\\t\\t\\t\\t><span class=\\"space-logo\\">\\n\\t\\t\\t\\t\\t\\t\\t\\t<img src={space_logo} alt=\\"Hugging Face Space\\" />\\n\\t\\t\\t\\t\\t\\t\\t</span> Spaces</a\\n\\t\\t\\t\\t\\t\\t>\\n\\t\\t\\t\\t\\t</span>\\n\\t\\t\\t\\t</div>\\n\\t\\t\\t{/if}\\n\\t\\t</div>\\n\\t</main>\\n</div>\\n\\n<style>\\n\\t.nav-holder {\\n\\t\\tpadding: var(--size-2) 0;\\n\\t\\tborder-bottom: solid 1px var(--border-color-primary);\\n\\t}\\n\\tnav {\\n\\t\\tdisplay: flex;\\n\\t\\tflex-wrap: wrap;\\n\\t\\tgap: var(--size-2);\\n\\t\\tjustify-content: flex-end;\\n\\t\\tmargin: 0 auto;\\n\\t\\tpadding: 0 var(--size-8);\\n\\t}\\n\\tnav a,\\n\\tbutton {\\n\\t\\tpadding: var(--size-1) var(--size-2);\\n\\t\\tborder-radius: var(--block-radius);\\n\\t\\tborder-width: var(--block-border-width);\\n\\t\\tborder-color: transparent;\\n\\t\\tcolor: var(--body-text-color-subdued);\\n\\t}\\n\\tnav a.active,\\n\\tbutton.active {\\n\\t\\tcolor: var(--body-text-color);\\n\\t\\tborder-color: var(--block-border-color);\\n\\t\\tbackground-color: var(--block-background-fill);\\n\\t}\\n\\t.gradio-container-5-44-1 {\\n\\t\\tdisplay: flex;\\n\\t\\tposition: relative;\\n\\t\\tflex-direction: column;\\n\\t\\tpadding: 0;\\n\\t\\tmin-height: 1px;\\n\\t\\toverflow: hidden;\\n\\t\\tcolor: var(--button-secondary-text-color);\\n\\t}\\n\\n\\t.embed-container {\\n\\t\\tmargin: var(--size-4) 0px;\\n\\t\\tborder: 1px solid var(--button-secondary-border-color);\\n\\t\\tborder-radius: var(--embed-radius);\\n\\t}\\n\\n\\t.with-info {\\n\\t\\tpadding-bottom: var(--size-7);\\n\\t}\\n\\n\\t.embed-container > main {\\n\\t\\tpadding: var(--size-4);\\n\\t}\\n\\n\\tmain {\\n\\t\\tdisplay: flex;\\n\\t\\tflex-grow: 1;\\n\\t\\tflex-direction: column;\\n\\t}\\n\\n\\t.app {\\n\\t\\tposition: relative;\\n\\t\\tmargin: auto;\\n\\t\\tpadding: var(--size-4) var(--size-8);\\n\\t\\twidth: 100%;\\n\\t\\theight: 100%;\\n\\t}\\n\\n\\t@media (min-width: 640px) {\\n\\t\\t.fillable:not(.fill_width) {\\n\\t\\t\\tmax-width: 640px;\\n\\t\\t}\\n\\t}\\n\\t@media (min-width: 768px) {\\n\\t\\t.fillable:not(.fill_width) {\\n\\t\\t\\tmax-width: 768px;\\n\\t\\t}\\n\\t}\\n\\t@media (min-width: 1024px) {\\n\\t\\t.fillable:not(.fill_width) {\\n\\t\\t\\tmax-width: 1024px;\\n\\t\\t}\\n\\t}\\n\\t@media (min-width: 1280px) {\\n\\t\\t.fillable:not(.fill_width) {\\n\\t\\t\\tmax-width: 1280px;\\n\\t\\t}\\n\\t}\\n\\t@media (min-width: 1536px) {\\n\\t\\t.fillable:not(.fill_width) {\\n\\t\\t\\tmax-width: 1536px;\\n\\t\\t}\\n\\t}\\n\\t@media (min-width: 1920px) {\\n\\t\\t.fillable:not(.fill_width) {\\n\\t\\t\\tmax-width: 1920px;\\n\\t\\t}\\n\\t}\\n\\n\\t.info {\\n\\t\\tdisplay: flex;\\n\\t\\tposition: absolute;\\n\\t\\tbottom: 0;\\n\\t\\tjustify-content: flex-start;\\n\\t\\tborder-top: 1px solid var(--button-secondary-border-color);\\n\\t\\tpadding: var(--size-1) var(--size-5);\\n\\t\\twidth: 100%;\\n\\t\\tcolor: var(--body-text-color-subdued);\\n\\t\\tfont-size: var(--text-md);\\n\\t\\twhite-space: nowrap;\\n\\t}\\n\\n\\t.info > span {\\n\\t\\tword-wrap: break-word;\\n\\t\\t-break: keep-all;\\n\\t\\tdisplay: block;\\n\\t\\tword-break: keep-all;\\n\\t}\\n\\n\\t.info > span:nth-child(1) {\\n\\t\\tmargin-right: 4px;\\n\\t\\tmin-width: 0px;\\n\\t\\tmax-width: max-content;\\n\\t\\toverflow: hidden;\\n\\t\\tcolor: var(--body-text-color);\\n\\t\\ttext-overflow: ellipsis;\\n\\t\\twhite-space: nowrap;\\n\\t}\\n\\n\\t.info > span:nth-child(2) {\\n\\t\\tmargin-right: 3px;\\n\\t}\\n\\n\\t.info > span:nth-child(2),\\n\\t.info > span:nth-child(3) {\\n\\t\\twidth: max-content;\\n\\t}\\n\\n\\t.info > span:nth-child(3) {\\n\\t\\talign-self: flex-end;\\n\\t\\tjustify-self: flex-end;\\n\\t\\tmargin-left: auto;\\n\\t\\ttext-align: right;\\n\\t}\\n\\n\\t.info > span:nth-child(1) {\\n\\t\\tflex-shrink: 9;\\n\\t}\\n\\n\\t.hidden-title {\\n\\t\\tposition: absolute;\\n\\t\\tleft: var(--size-5);\\n\\t\\topacity: 0;\\n\\t\\tbackground: var(--button-secondary-background-fill);\\n\\t\\tpadding-right: 4px;\\n\\t}\\n\\n\\t.info a {\\n\\t\\tcolor: var(--body-text-color);\\n\\t}\\n\\n\\t.title {\\n\\t\\tfont-size: var(--text-sm);\\n\\t\\tfont-family: var(--font-mono);\\n\\t}\\n\\n\\t.hf {\\n\\t\\tmargin-left: 5px;\\n\\t}\\n\\n\\t.space-logo img {\\n\\t\\tdisplay: inline-block;\\n\\t\\tmargin-bottom: 4px;\\n\\t\\theight: 12px;\\n\\t}\\n\\n\\tmain a:hover {\\n\\t\\ttext-decoration: underline;\\n\\t}</style>\\n"],"names":[],"mappings":"AAmFC,yCAAY,CACX,OAAO,CAAE,IAAI,QAAQ,CAAC,CAAC,CAAC,CACxB,aAAa,CAAE,KAAK,CAAC,GAAG,CAAC,IAAI,sBAAsB,CACpD,CACA,iCAAI,CACH,OAAO,CAAE,IAAI,CACb,SAAS,CAAE,IAAI,CACf,GAAG,CAAE,IAAI,QAAQ,CAAC,CAClB,eAAe,CAAE,QAAQ,CACzB,MAAM,CAAE,CAAC,CAAC,IAAI,CACd,OAAO,CAAE,CAAC,CAAC,IAAI,QAAQ,CACxB,CACA,kBAAG,CAAC,gBAAC,CACL,oCAAO,CACN,OAAO,CAAE,IAAI,QAAQ,CAAC,CAAC,IAAI,QAAQ,CAAC,CACpC,aAAa,CAAE,IAAI,cAAc,CAAC,CAClC,YAAY,CAAE,IAAI,oBAAoB,CAAC,CACvC,YAAY,CAAE,WAAW,CACzB,KAAK,CAAE,IAAI,yBAAyB,CACrC,CACA,kBAAG,CAAC,CAAC,sBAAO,CACZ,MAAM,qCAAQ,CACb,KAAK,CAAE,IAAI,iBAAiB,CAAC,CAC7B,YAAY,CAAE,IAAI,oBAAoB,CAAC,CACvC,gBAAgB,CAAE,IAAI,uBAAuB,CAC9C,CACA,sDAAyB,CACxB,OAAO,CAAE,IAAI,CACb,QAAQ,CAAE,QAAQ,CAClB,cAAc,CAAE,MAAM,CACtB,OAAO,CAAE,CAAC,CACV,UAAU,CAAE,GAAG,CACf,QAAQ,CAAE,MAAM,CAChB,KAAK,CAAE,IAAI,6BAA6B,CACzC,CAEA,8CAAiB,CAChB,MAAM,CAAE,IAAI,QAAQ,CAAC,CAAC,GAAG,CACzB,MAAM,CAAE,GAAG,CAAC,KAAK,CAAC,IAAI,+BAA+B,CAAC,CACtD,aAAa,CAAE,IAAI,cAAc,CAClC,CAEA,wCAAW,CACV,cAAc,CAAE,IAAI,QAAQ,CAC7B,CAEA,+BAAgB,CAAG,mBAAK,CACvB,OAAO,CAAE,IAAI,QAAQ,CACtB,CAEA,kCAAK,CACJ,OAAO,CAAE,IAAI,CACb,SAAS,CAAE,CAAC,CACZ,cAAc,CAAE,MACjB,CAEA,kCAAK,CACJ,QAAQ,CAAE,QAAQ,CAClB,MAAM,CAAE,IAAI,CACZ,OAAO,CAAE,IAAI,QAAQ,CAAC,CAAC,IAAI,QAAQ,CAAC,CACpC,KAAK,CAAE,IAAI,CACX,MAAM,CAAE,IACT,CAEA,MAAO,YAAY,KAAK,CAAE,CACzB,uCAAS,KAAK,WAAW,CAAE,CAC1B,SAAS,CAAE,KACZ,CACD,CACA,MAAO,YAAY,KAAK,CAAE,CACzB,uCAAS,KAAK,WAAW,CAAE,CAC1B,SAAS,CAAE,KACZ,CACD,CACA,MAAO,YAAY,MAAM,CAAE,CAC1B,uCAAS,KAAK,WAAW,CAAE,CAC1B,SAAS,CAAE,MACZ,CACD,CACA,MAAO,YAAY,MAAM,CAAE,CAC1B,uCAAS,KAAK,WAAW,CAAE,CAC1B,SAAS,CAAE,MACZ,CACD,CACA,MAAO,YAAY,MAAM,CAAE,CAC1B,uCAAS,KAAK,WAAW,CAAE,CAC1B,SAAS,CAAE,MACZ,CACD,CACA,MAAO,YAAY,MAAM,CAAE,CAC1B,uCAAS,KAAK,WAAW,CAAE,CAC1B,SAAS,CAAE,MACZ,CACD,CAEA,mCAAM,CACL,OAAO,CAAE,IAAI,CACb,QAAQ,CAAE,QAAQ,CAClB,MAAM,CAAE,CAAC,CACT,eAAe,CAAE,UAAU,CAC3B,UAAU,CAAE,GAAG,CAAC,KAAK,CAAC,IAAI,+BAA+B,CAAC,CAC1D,OAAO,CAAE,IAAI,QAAQ,CAAC,CAAC,IAAI,QAAQ,CAAC,CACpC,KAAK,CAAE,IAAI,CACX,KAAK,CAAE,IAAI,yBAAyB,CAAC,CACrC,SAAS,CAAE,IAAI,SAAS,CAAC,CACzB,WAAW,CAAE,MACd,CAEA,oBAAK,CAAG,mBAAK,CACZ,SAAS,CAAE,UAAU,CACrB,MAAM,CAAE,QAAQ,CAChB,OAAO,CAAE,KAAK,CACd,UAAU,CAAE,QACb,CAEA,oBAAK,CAAG,mBAAI,WAAW,CAAC,CAAE,CACzB,YAAY,CAAE,GAAG,CACjB,SAAS,CAAE,GAAG,CACd,SAAS,CAAE,WAAW,CACtB,QAAQ,CAAE,MAAM,CAChB,KAAK,CAAE,IAAI,iBAAiB,CAAC,CAC7B,aAAa,CAAE,QAAQ,CACvB,WAAW,CAAE,MACd,CAEA,oBAAK,CAAG,mBAAI,WAAW,CAAC,CAAE,CACzB,YAAY,CAAE,GACf,CAEA,oBAAK,CAAG,mBAAI,WAAW,CAAC,CAAC,CACzB,oBAAK,CAAG,mBAAI,WAAW,CAAC,CAAE,CACzB,KAAK,CAAE,WACR,CAEA,oBAAK,CAAG,mBAAI,WAAW,CAAC,CAAE,CACzB,UAAU,CAAE,QAAQ,CACpB,YAAY,CAAE,QAAQ,CACtB,WAAW,CAAE,IAAI,CACjB,UAAU,CAAE,KACb,CAEA,oBAAK,CAAG,mBAAI,WAAW,CAAC,CAAE,CACzB,WAAW,CAAE,CACd,CAEA,2CAAc,CACb,QAAQ,CAAE,QAAQ,CAClB,IAAI,CAAE,IAAI,QAAQ,CAAC,CACnB,OAAO,CAAE,CAAC,CACV,UAAU,CAAE,IAAI,kCAAkC,CAAC,CACnD,aAAa,CAAE,GAChB,CAEA,oBAAK,CAAC,gBAAE,CACP,KAAK,CAAE,IAAI,iBAAiB,CAC7B,CAEA,oCAAO,CACN,SAAS,CAAE,IAAI,SAAS,CAAC,CACzB,WAAW,CAAE,IAAI,WAAW,CAC7B,CAEA,iCAAI,CACH,WAAW,CAAE,GACd,CAEA,0BAAW,CAAC,kBAAI,CACf,OAAO,CAAE,YAAY,CACrB,aAAa,CAAE,GAAG,CAClB,MAAM,CAAE,IACT,CAEA,mBAAI,CAAC,gBAAC,MAAO,CACZ,eAAe,CAAE,SAClB"}'},Xs=create_ssr_component((e,t,n,r)=>{let i,o;o=subscribe(xt$2,N=>i=N);let{wrapper:s}=t,{version:a}=t,{initial_height:u}=t,{fill_width:c}=t,{is_embed:l}=t,{is_lite:f}=t,{space:h}=t,{display:_}=t,{info:m}=t,{loaded:B}=t,{pages:C=[]}=t,{current_page:k=""}=t,{root:L}=t;return getContext("set_lite_page"),t.wrapper===void 0&&n.wrapper&&s!==void 0&&n.wrapper(s),t.version===void 0&&n.version&&a!==void 0&&n.version(a),t.initial_height===void 0&&n.initial_height&&u!==void 0&&n.initial_height(u),t.fill_width===void 0&&n.fill_width&&c!==void 0&&n.fill_width(c),t.is_embed===void 0&&n.is_embed&&l!==void 0&&n.is_embed(l),t.is_lite===void 0&&n.is_lite&&f!==void 0&&n.is_lite(f),t.space===void 0&&n.space&&h!==void 0&&n.space(h),t.display===void 0&&n.display&&_!==void 0&&n.display(_),t.info===void 0&&n.info&&m!==void 0&&n.info(m),t.loaded===void 0&&n.loaded&&B!==void 0&&n.loaded(B),t.pages===void 0&&n.pages&&C!==void 0&&n.pages(C),t.current_page===void 0&&n.current_page&&k!==void 0&&n.current_page(k),t.root===void 0&&n.root&&L!==void 0&&n.root(L),e.css.add(wo),o(),`<div class="${["gradio-container gradio-container-"+escape(a,!0)+" svelte-16faplo",(c?"fill_width":"")+" "+(_?"embed-container":"")+" "+(m?"with-info":"")].join(" ").trim()}" data-iframe-height${add_styles({"min-height":B?"initial":u,"flex-grow":_?"auto":"1"})}${add_attribute("this",s,0)}>${C.length>1?`<div class="nav-holder svelte-16faplo"><nav class="${["fillable svelte-16faplo",c?"fill_width":""].join(" ").trim()}">${each(C,([N,D],j)=>`${f?`<button class="${["svelte-16faplo",N===k?"active":""].join(" ").trim()}">${escape(D)} </button>`:`<a${add_attribute("href",`${L}/${N}`,0)} data-sveltekit-reload class="${["svelte-16faplo",N===k?"active":""].join(" ").trim()}">${escape(D)} </a>`}`)}</nav></div>`:""} <main class="${["fillable svelte-16faplo",(c?"fill_width":"")+" "+(!_&&!l?"app":"")].join(" ").trim()}">${r.default?r.default({}):""} <div>${_&&h&&m?`<div class="info svelte-16faplo"><span class="svelte-16faplo"><a href="${"https://huggingface.co/spaces/"+escape(h,!0)}" class="title svelte-16faplo">${escape(h)}</a></span> <span class="svelte-16faplo">${escape(i("common.built_with"))} <a class="gradio svelte-16faplo" href="https://gradio.app" data-svelte-h="svelte-jht9bl">Gradio</a>.</span> <span class="svelte-16faplo">${escape(i("common.hosted_on"))} <a class="hf svelte-16faplo" href="https://huggingface.co/spaces" data-svelte-h="svelte-d5sowi"><span class="space-logo svelte-16faplo"><img${add_attribute("src",Tr$1,0)} alt="Hugging Face Space" class="svelte-16faplo"></span> Spaces</a></span></div>`:""}</div></main> </div>`});let Un=!1;typeof window<"u"&&"attachShadow"in Element.prototype&&"adoptedStyleSheets"in Document.prototype&&(Un="adoptedStyleSheets"in document.createElement("div").attachShadow({mode:"open"}));function Ks(e,t){const n=new URL(import.meta.url).origin;var r=e;if(window.location.origin!==n&&(r=new URL(e,n).href),document.querySelector(`link[href='${r}']`))return Promise.resolve();const o=document.createElement("link");return o.rel="stylesheet",o.href=r,new Promise((s,a)=>{o.addEventListener("load",()=>s()),o.addEventListener("error",()=>{console.error(`Unable to preload CSS for ${r}`),s();}),t.appendChild(o);})}function Zs(e,t,n){if(!Un)return e;n||(n=document.createElement("style")),n.remove();const r=new CSSStyleSheet;r.replaceSync(e);let i="";e=e.replace(/@import\s+url\((.*?)\);\s*/g,(u,c)=>(i+=`@import url(${c});
`,""));const o=r.cssRules;let s="",a=`.gradio-container.gradio-container-${t} .contain `;for(let u=0;u<o.length;u++){const c=o[u];let l=c.cssText.includes(".dark");if(c instanceof CSSStyleRule){const f=c.selectorText;if(f){const h=f.replace(".dark","").split(",").map(_=>`${l?".dark":""} ${a} ${_.trim()} `).join(",");s+=c.cssText,s+=c.cssText.replace(f,h);}}else if(c instanceof CSSMediaRule){let f=`@media ${c.media.mediaText} {`;for(let h=0;h<c.cssRules.length;h++){const _=c.cssRules[h];if(_ instanceof CSSStyleRule){let m=_.cssText.includes(".dark ");const B=_.selectorText,C=B.replace(".dark","").split(",").map(k=>`${m?".dark":""} ${a} ${k.trim()} `).join(",");f+=_.cssText.replace(B,C);}}f+="}",s+=f;}else if(c instanceof CSSKeyframesRule){s+=`@keyframes ${c.name} {`;for(let f=0;f<c.cssRules.length;f++){const h=c.cssRules[f];h instanceof CSSKeyframeRule&&(s+=`${h.keyText} { ${h.style.cssText} }`);}s+="}";}else c instanceof CSSFontFaceRule&&(s+=`@font-face { ${c.style.cssText} }`);}return i+s}var Qt$2=Object.prototype.hasOwnProperty;function Xt$3(e,t,n){for(n of e.keys())if(Ne$1(n,t))return n}function Ne$1(e,t){var n,r,i;if(e===t)return !0;if(e&&t&&(n=e.constructor)===t.constructor){if(n===Date)return e.getTime()===t.getTime();if(n===RegExp)return e.toString()===t.toString();if(n===Array){if((r=e.length)===t.length)for(;r--&&Ne$1(e[r],t[r]););return r===-1}if(n===Set){if(e.size!==t.size)return !1;for(r of e)if(i=r,i&&typeof i=="object"&&(i=Xt$3(t,i),!i)||!t.has(i))return !1;return !0}if(n===Map){if(e.size!==t.size)return !1;for(r of e)if(i=r[0],i&&typeof i=="object"&&(i=Xt$3(t,i),!i)||!Ne$1(r[1],t.get(i)))return !1;return !0}if(n===ArrayBuffer)e=new Uint8Array(e),t=new Uint8Array(t);else if(n===DataView){if((r=e.byteLength)===t.byteLength)for(;r--&&e.getInt8(r)===t.getInt8(r););return r===-1}if(ArrayBuffer.isView(e)){if((r=e.byteLength)===t.byteLength)for(;r--&&e[r]===t[r];);return r===-1}if(!n||typeof e=="object"){r=0;for(n in e)if(Qt$2.call(e,n)&&++r&&!Qt$2.call(t,n)||!(n in t)||!Ne$1(e[n],t[n]))return !1;return Object.keys(t).length===r}}return e!==e&&t!==t}const Co={accordion:{component:()=>import('./Index41-D7bdXrHI.js')},annotatedimage:{component:()=>import('./Index20-Dgt9OSAm.js')},audio:{base:()=>import('./StaticAudio-DaQstrPw.js'),example:()=>import('./Example4-7u--UOCG.js'),component:()=>import('./index21-VOT2bICO.js')},box:{component:()=>import('./Index6-BTjbR_mc.js')},browserstate:{component:()=>import('./Index65-HsorsYbY.js')},button:{component:()=>Promise.resolve().then(function () { return Index34; })},chatbot:{component:()=>import('./Index63-BKkaBrPG.js')},checkbox:{example:()=>import('./Example5-BY36bKUd.js'),component:()=>import('./Index42-CvnAeKY0.js')},checkboxgroup:{example:()=>import('./Example6-CtF03CXA.js'),component:()=>import('./Index22-7cP0McNf.js')},code:{example:()=>import('./Example7-BgAxc6bX.js'),component:()=>import('./Index16-BKwrbaLU.js').then(e=>e.K)},colorpicker:{example:()=>import('./Example8-DUw5ngWN.js'),component:()=>import('./Index51-msi4bIzZ.js')},column:{component:()=>Promise.resolve().then(function () { return Index19; })},core:{component:()=>import('./index-CuEPIRZi.js')},dataframe:{example:()=>import('./Example9-DbSY_4re.js'),component:()=>import('./Index64-Dj6MSvQI.js')},dataset:{component:()=>import('./Index23-BlOyHfXf.js')},datetime:{example:()=>import('./Example-CmZTmcbg.js'),component:()=>import('./Index56-DXlQCcsP.js')},dialogue:{example:()=>import('./Example11-DKMNurZL.js'),component:()=>import('./Index57-CoAHiGif.js')},downloadbutton:{component:()=>import('./Index43-BVm15iFW.js')},draggable:{component:()=>import('./Index25-DjREZ82E.js')},dropdown:{example:()=>import('./Example12-Dm_QueAJ.js'),component:()=>import('./Index58-wTLDWoWP.js')},file:{example:()=>import('./Example13-QUrFCQ6n.js'),component:()=>import('./Index10-cn2tMAXv.js')},fileexplorer:{example:()=>import('./Example14-DvaAOKL5.js'),component:()=>import('./Index62-D1pMVn2U.js')},form:{component:()=>Promise.resolve().then(function () { return Index18; })},gallery:{base:()=>import('./Gallery-D2TaXXwi.js'),component:()=>import('./Index9-DdzGEbAA.js')},group:{component:()=>import('./Index26-yqg76A6k.js')},highlightedtext:{component:()=>import('./Index61-CpRmTJgG.js')},html:{base:()=>import('./Index52-FVlN4byD.js'),example:()=>import('./Example15-BX_Nds0Q.js'),component:()=>import('./Index52-FVlN4byD.js')},image:{base:()=>import('./ImagePreview-CqoVGso6.js'),example:()=>import('./Example10-CU7gPScC.js'),component:()=>import('./Index27-BVlCZAZD.js')},imageeditor:{example:()=>import('./Example16-Bl3zg2_g.js'),component:()=>import('./Index3-C7q7p7ZL.js').then(e=>e.as)},imageslider:{example:()=>import('./Example17-BSaUMSck.js'),component:()=>import('./Index66-nG2maPfk.js')},json:{example:()=>import('./Example18-D2B_1gud.js'),component:()=>import('./Index11-DWSahVF-.js')},label:{component:()=>import('./Index44-Cr9dXVBZ.js')},markdown:{example:()=>import('./Example19-Tvj9Ljos.js'),component:()=>import('./Index53-B1WTLUqz.js')},model3d:{example:()=>import('./Example20-7u--UOCG.js'),component:()=>import('./Index59-N3ledUQG.js')},multimodaltextbox:{example:()=>import('./Example21-k6K20lI0.js'),component:()=>import('./Index45-BaUiSjrH.js')},nativeplot:{example:()=>import('./Example2-Biy8EGGC.js'),component:()=>import('./Index28-C_N20m2x.js')},number:{example:()=>import('./Example22-C9X-oh6t.js'),component:()=>import('./Index29-DRClzvUQ.js')},paramviewer:{example:()=>import('./Example23-DUXZ9Y7A.js'),component:()=>import('./Index60-D3Gcs_4C.js')},plot:{base:()=>import('./Plot-DO1sCqky.js'),component:()=>import('./Index12-pNL67HIm.js')},radio:{example:()=>import('./Example24-DpqwuJHm.js'),component:()=>import('./Index54-YhOPpR69.js')},row:{component:()=>import('./Index30-DdkkAhMT.js')},sidebar:{component:()=>import('./Index46-CExn0dAy.js')},sketchbox:{component:()=>import('./Index31-7_fo2y5l.js')},slider:{example:()=>import('./Example25-DKMNurZL.js'),component:()=>import('./Index32-BPfsWrhU.js')},state:{component:()=>import('./Index13-D3zgy-z7.js')},statustracker:{component:()=>import('./index2-BBnWtO_p.js')},tabitem:{component:()=>import('./Index47-pE1MySyk.js')},tabs:{component:()=>import('./Index48-BdwCIiVI.js')},textbox:{example:()=>Promise.resolve().then(function () { return Example3; }),component:()=>Promise.resolve().then(function () { return Index24; })},timer:{component:()=>import('./Index14-DFvG43KK.js')},uploadbutton:{component:()=>import('./Index49-DJ21Lu8h.js')},vibeeditor:{component:()=>import('./Index33-BiXJqAur.js')},video:{base:()=>import('./VideoPreview-CAkGW-JA.js').then(e=>e.b),example:()=>import('./Example26-XWYWagY2.js'),component:()=>import('./index55-Cz6gYVCN.js')}},le$1={},St$2=typeof window<"u";function Kt$2({api_url:e,name:t,id:n,variant:r}){const i=St$2&&window.__GRADIO__CC__,o={...Co,...i||{}};let s=n||t;if(le$1[`${s}-${r}`])return {component:le$1[`${s}-${r}`],name:t};try{if(!o?.[s]?.[r]&&!o?.[t]?.[r])throw new Error;return le$1[`${s}-${r}`]=(o?.[s]?.[r]||o?.[t]?.[r])(),{name:t,component:le$1[`${s}-${r}`]}}catch{if(!s)throw new Error(`Component not found: ${t}`);try{return le$1[`${s}-${r}`]=Eo(e,s,r),{name:t,component:le$1[`${s}-${r}`]}}catch(u){if(r==="example")return le$1[`${s}-${r}`]=import('./Example27-DKMNurZL.js'),{name:t,component:le$1[`${s}-${r}`]};throw console.error(`failed to load: ${t}`),console.error(u),u}}}function Zt$2(e){return St$2?new Promise((t,n)=>{const r=document.createElement("link");r.rel="stylesheet",r.href=e,document.head.appendChild(r),r.onload=()=>t(),r.onerror=()=>n();}):Promise.resolve()}function Eo(e,t,n){const r=St$2?"client":"server";let i;return r==="server"?Promise.all([Zt$2(`${e}/custom_component/${t}/${n}/style.css`),import('./Index50-CRW_bCag.js')]).then(([o,s])=>s):(i=`${e}/custom_component/${t}/${r}/${n}/index.js`,Promise.all([Zt$2(`${e}/custom_component/${t}/${r}/${n}/style.css`),import(i)]).then(([o,s])=>s))}function xo(){const e=writable({}),t={},n={},r=new Map,i=new Map,o=new Map,s={};function a({fn_index:c,status:l,queue:f=!0,size:h,position:_=null,eta:m=null,message:B=null,progress:C,time_limit:k=null}){const L=n[c],N=t[c],D=s[c],j=L.map(P=>{let R;const G=r.get(P)||0;if(D==="pending"&&l!=="pending"){let W=G-1;r.set(P,W<0?0:W),R=W>0?"pending":l;}else D==="pending"&&l==="pending"?R="pending":D!=="pending"&&l==="pending"?(R="pending",r.set(P,G+1)):R=l;return {id:P,queue_position:_,queue_size:h,eta:m,status:R,message:B,progress:C}});N.forEach(P=>{const R=i.get(P)||0;if(D==="pending"&&l!=="pending"){let G=R-1;i.set(P,G<0?0:G),o.set(P,l);}else D!=="pending"&&l==="pending"?(i.set(P,R+1),o.set(P,l)):o.delete(P);}),e.update(P=>(j.forEach(({id:R,queue_position:G,queue_size:W,eta:ge,status:v,message:be,progress:K})=>{P[R]={queue:f,queue_size:W,queue_position:G,eta:ge,message:be,progress:K,status:v,fn_index:c};}),P)),s[c]=l;}function u(c,l,f){t[c]=l,n[c]=f;}return {update:a,register:u,subscribe:e.subscribe,get_status_for_fn(c){return s[c]},get_inputs_to_update(){return o}}}let pe$2=[];const So=typeof window<"u",Yt$2=So?requestAnimationFrame:async e=>await e();function Ys({initial_layout:e=void 0}={initial_layout:void 0}){let t,n=writable({}),r={},i,o,s,a,u=xo();const c=writable(e);let l=[],f,h={},_,m=null;function B(g){m=g;}let C,k;function L(g){g.forEach(b=>{b.targets.forEach(E=>{const p=a[E[0]];p&&b.event_specific_args?.length>0&&b.event_specific_args?.forEach(A=>{p.props[A]=b[A];});});});}async function N({app:g,components:b,layout:E,dependencies:p,root:A,options:y}){ge(),f=g,a&&b.forEach(d=>{if(d.props.value==null&&d.key){const T=Object.values(a).find(O=>O.key===d.key);T&&(d.props.value=T.props.value);}}),l=b,i=new Set,o=new Set,pe$2=[],s=new Map,t=new Map,a={},C=E,k=A,_={id:E.id,type:"column",props:{interactive:!1,scale:y.fill_height?1:null},has_modes:!1,instance:null,component:null,component_class_id:"",key:null},b.push(_),p.forEach(d=>{u.register(d.id,d.inputs,d.show_progress_on||d.outputs),d.frontend_fn=Jt$2(d.js,!!d.backend_fn,d.inputs.length,d.outputs.length),en$2(d.targets,d.id,r),tn$2(d,i,o);}),n.set(r),s=nn$2(b,E,A),a=b.reduce((d,T)=>(d[T.id]=T,d),{}),await j(E,A,l),c.set(_),L(p);}function D({render_id:g,components:b,layout:E,root:p,dependencies:A}){b.forEach(w=>{for(const V in w.props)w.props[V]===null&&(w.props[V]=void 0);});let y=[],d=[];b.forEach(w=>{w.key==null||!h[g]?.includes(w.key)?d.push(w):y.push(w);}),nn$2(d,E,p).forEach((w,V)=>{s.set(V,w);}),r={},A.forEach(w=>{u.register(w.id,w.inputs,w.outputs),w.frontend_fn=Jt$2(w.js,!!w.backend_fn,w.inputs.length,w.outputs.length),en$2(w.targets,w.id,r),tn$2(w,i,o);}),n.set(r);let O=a[E.id];const Z=w=>{w.children&&w.children.forEach(V=>{Z(V);});};Z(O),Object.entries(a).forEach(([w,V])=>{let Be=Number(w);if(V.rendered_in===g){let ae=y.find(ie=>ie.key===V.key);if(V.key!=null&&ae!==void 0){const ie=a[V.id];for(const ve in ae.props)ae.props.preserved_by_key?.includes(ve)||(ie.props[ve]=ae.props[ve]);}else delete a[Be],t.has(Be)&&t.delete(Be);}}),d.concat(y.filter(w=>!a[w.id])).forEach(w=>{a[w.id]=w,t.set(w.id,w);}),O.parent&&(O.parent.children[O.parent.children.indexOf(O)]=a[E.id]),j(E,p,l.concat(b),O.parent).then(()=>{c.set(_),h[g]=b.map(w=>w.key).filter(w=>w!=null);}),L(A);}async function j(g,b,E,p){const A=a[g.id];if(!A.component){const y=A.component_class_id||A.type;let d=s.get(y);d&&(A.component=(await d)?.default);}if(A.parent=p,A.type==="dataset"&&(A.props.component_map=bt$3(A.type,A.component_class_id,b,E,A.props.components).example_components),r[A.id]&&(A.props.attached_events=Object.keys(r[A.id])),A.props.interactive=To(A.id,A.props.interactive,A.props.value,i,o),A.props.server=Oo(A.id,A.props.server_fns,f),t.set(A.id,A),g.children&&(A.children=await Promise.all(g.children.map(y=>j(y,b,E,A)))),A.type==="tabs"&&!A.props.initial_tabs){const d=(g.children?.map((T,O)=>{const Z=a[T.id];return Z.props.id??=T.id,{type:Z.type,props:{...Z.props,id:Z.props.id,order:O}}})||[]).filter(T=>T.type==="tabitem");A.props.initial_tabs=d?.map(T=>({label:T.props.label,id:T.props.id,visible:typeof T.props.visible=="boolean"?T.props.visible:!0,interactive:T.props.interactive,order:T.props.order}));}return A.type==="tabs"&&g.children?.forEach((y,d)=>{const T=a[y.id];T.props.order=d;}),A}let P=!1,R=writable(!1);async function G(g,b){if(g.size===0)return;const E=b.filter(p=>g.has(p.id));for(const p of E){const A=p.component_class_id||p.type;if(s.has(A))p.component=(await s.get(A))?.default??p.component;else {const{component:y,example_components:d}=bt$3(p.type,p.component_class_id,k,b);if(s.set(A,y),d)for(const[T,O]of d)s.set(T,O);p.component||(p.component=(await y)?.default);}}}function W(g){return g.some(b=>b.some(E=>{const p=a[E.id];return p?E.prop==="visible"||E.prop==="selected"&&p.type==="tabs":!1}))}function ge(){const g=W(pe$2);let b;const E=t?[...t.values()]:l;g&&C&&(b=We$2(C,E)),c.update(p=>{for(let A=0;A<pe$2.length;A++)for(let y=0;y<pe$2[A].length;y++){const d=pe$2[A][y];if(!d)continue;const T=a[d.id];if(!T)continue;let O;const Z=T.props[d.prop];d.value instanceof Map?O=new Map(d.value):d.value instanceof Set?O=new Set(d.value):Array.isArray(d.value)?O=[...d.value]:d.value==null?O=null:typeof d.value=="object"?O={...d.value}:O=d.value,T.props[d.prop]=O,d.prop==="value"&&!jn(T)&&!Ne$1(Z,O)&&m?.(d.id,O);}return p}),g&&C&&b&&Yt$2(async()=>{const p=We$2(C,E),A=new Set;for(const y of p)b.has(y)||A.add(y);await G(A,E),A.size>0&&c.update(y=>y);}),pe$2=[],P=!1,R.set(!1);}function v(g){g&&(pe$2.push(g),P||(P=!0,R.set(!0),Yt$2(ge)));}function be(g){let b=t.get(g);if(!b){const E=get_store_value(c);b=K(E,g);}return b?b.instance?.get_value?b.instance.get_value():b.props.value:null}function K(g,b){if(g.id===b)return g;if(g.children)for(const E of g.children){const p=K(E,b);if(p)return p}}function Ze(g,b){const E=t.get(g);E&&E.instance?.modify_stream_state&&E.instance.modify_stream_state(b);}function F(g){const b=t.get(g);return b?.instance?.get_stream_state?b.instance.get_stream_state():"not_set"}function se(g,b){const E=t.get(g);E?.instance?.set_time_limit&&E.instance.set_time_limit(b);}return {layout:c,targets:n,update_value:v,get_data:be,modify_stream:Ze,get_stream_state:F,set_time_limit:se,loading_status:u,scheduled_updates:R,create_layout:N,rerender_layout:D,value_change:B}}const Bo=Object.getPrototypeOf(async function(){}).constructor;function Jt$2(e,t,n,r){if(!e||e===!0)return null;const i=t?n===1:r===1;try{return new Bo("__fn_args",`  let result = await (${e})(...__fn_args);
  if (typeof result === "undefined") return [];
  return (${i} && !Array.isArray(result)) ? [result] : result;`)}catch(o){return console.error("Could not parse custom js method."),console.error(o),null}}function en$2(e,t,n){return e.forEach(([r,i])=>{n[r]||(n[r]={}),n[r]?.[i]&&!n[r]?.[i].includes(t)?n[r][i].push(t):n[r][i]=[t];}),n}function tn$2(e,t,n){return e.inputs.forEach(r=>t.add(r)),e.outputs.forEach(r=>n.add(r)),[t,n]}function Io(e){return Array.isArray(e)&&e.length===0||e===""||e===0||!e}function To(e,t,n,r,i){return t===!1?!1:t===!0?!0:!!(r.has(e)||!i.has(e)&&Io(n))}function Oo(e,t,n){return t?t.reduce((r,i)=>(r[i]=async(...o)=>(o.length===1&&(o=o[0]),await n.component_server(e,i,o)),r),{}):{}}function bt$3(e,t,n,r,i){let o=new Map;e==="api"&&(e="state"),e==="dataset"&&i&&i.forEach(a=>{if(o.has(a))return;let u;const c=r.find(l=>l.type===a);c&&(u=Kt$2({api_url:n,name:a,id:c.component_class_id,variant:"example"}),o.set(a,u.component));});const s=Kt$2({api_url:n,name:e,id:t,variant:"component"});return {component:s.component,name:s.name,example_components:o.size>0?o:void 0}}function Ho(e,t,n){const r=n?.selected_tab_id===e.id||n?.selected_tab_id===e.props.id;return t&&r}function Po(e,t,n){const r=e.props.selected;if(typeof r=="string"||typeof r=="number")return r;if(t.children)for(const i of t.children){const o=n.find(s=>s.id===i.id);if(o?.type==="tabitem"&&o.props.visible!==!1&&o.props.interactive!==!1)return o.id||o.props.id}}function st$3(e,t,n){const r=new Set;if(e.children)for(const i of e.children)We$2(i,t,!0,n).forEach(s=>r.add(s));return r}function We$2(e,t,n=!0,r){const i=new Set,o=t.find(a=>a.id===e.id);if(!o)return i;const s=n&&(typeof o.props.visible=="boolean"?o.props.visible:!0);if(o.type==="tabitem")return Ho(o,s,r)&&(i.add(o.id),st$3(e,t,r).forEach(u=>i.add(u))),i;if(o.type==="tabs"){if(s){i.add(o.id);const a=Po(o,e,t);st$3(e,t,{selected_tab_id:a}).forEach(c=>i.add(c));}return i}return s&&(i.add(o.id),st$3(e,t,r).forEach(u=>i.add(u))),i}function nn$2(e,t,n){let r=new Map;const i=We$2(t,e);return e.forEach(o=>{if(i.has(o.id)){const{component:s,example_components:a}=bt$3(o.type,o.component_class_id,n,e);if(r.set(o.component_class_id||o.type,s),a)for(const[u,c]of a)r.set(u,c);}}),r}function jn(e){return typeof e.props.visible=="boolean"&&e.props.visible===!1?!1:e.parent?jn(e.parent):!0}const Js=["red","green","blue","yellow","purple","teal","orange","cyan","lime","pink"],No=[{color:"red",primary:600,secondary:100},{color:"green",primary:600,secondary:100},{color:"blue",primary:600,secondary:100},{color:"yellow",primary:500,secondary:100},{color:"purple",primary:600,secondary:100},{color:"teal",primary:600,secondary:100},{color:"orange",primary:600,secondary:100},{color:"cyan",primary:600,secondary:100},{color:"lime",primary:500,secondary:100},{color:"pink",primary:600,secondary:100}],rn$2={inherit:"inherit",current:"currentColor",transparent:"transparent",black:"#000",white:"#fff",slate:{50:"#f8fafc",100:"#f1f5f9",200:"#e2e8f0",300:"#cbd5e1",400:"#94a3b8",500:"#64748b",600:"#475569",700:"#334155",800:"#1e293b",900:"#0f172a",950:"#020617"},gray:{50:"#f9fafb",100:"#f3f4f6",200:"#e5e7eb",300:"#d1d5db",400:"#9ca3af",500:"#6b7280",600:"#4b5563",700:"#374151",800:"#1f2937",900:"#111827",950:"#030712"},zinc:{50:"#fafafa",100:"#f4f4f5",200:"#e4e4e7",300:"#d4d4d8",400:"#a1a1aa",500:"#71717a",600:"#52525b",700:"#3f3f46",800:"#27272a",900:"#18181b",950:"#09090b"},neutral:{50:"#fafafa",100:"#f5f5f5",200:"#e5e5e5",300:"#d4d4d4",400:"#a3a3a3",500:"#737373",600:"#525252",700:"#404040",800:"#262626",900:"#171717",950:"#0a0a0a"},stone:{50:"#fafaf9",100:"#f5f5f4",200:"#e7e5e4",300:"#d6d3d1",400:"#a8a29e",500:"#78716c",600:"#57534e",700:"#44403c",800:"#292524",900:"#1c1917",950:"#0c0a09"},red:{50:"#fef2f2",100:"#fee2e2",200:"#fecaca",300:"#fca5a5",400:"#f87171",500:"#ef4444",600:"#dc2626",700:"#b91c1c",800:"#991b1b",900:"#7f1d1d",950:"#450a0a"},orange:{50:"#fff7ed",100:"#ffedd5",200:"#fed7aa",300:"#fdba74",400:"#fb923c",500:"#f97316",600:"#ea580c",700:"#c2410c",800:"#9a3412",900:"#7c2d12",950:"#431407"},amber:{50:"#fffbeb",100:"#fef3c7",200:"#fde68a",300:"#fcd34d",400:"#fbbf24",500:"#f59e0b",600:"#d97706",700:"#b45309",800:"#92400e",900:"#78350f",950:"#451a03"},yellow:{50:"#fefce8",100:"#fef9c3",200:"#fef08a",300:"#fde047",400:"#facc15",500:"#eab308",600:"#ca8a04",700:"#a16207",800:"#854d0e",900:"#713f12",950:"#422006"},lime:{50:"#f7fee7",100:"#ecfccb",200:"#d9f99d",300:"#bef264",400:"#a3e635",500:"#84cc16",600:"#65a30d",700:"#4d7c0f",800:"#3f6212",900:"#365314",950:"#1a2e05"},green:{50:"#f0fdf4",100:"#dcfce7",200:"#bbf7d0",300:"#86efac",400:"#4ade80",500:"#22c55e",600:"#16a34a",700:"#15803d",800:"#166534",900:"#14532d",950:"#052e16"},emerald:{50:"#ecfdf5",100:"#d1fae5",200:"#a7f3d0",300:"#6ee7b7",400:"#34d399",500:"#10b981",600:"#059669",700:"#047857",800:"#065f46",900:"#064e3b",950:"#022c22"},teal:{50:"#f0fdfa",100:"#ccfbf1",200:"#99f6e4",300:"#5eead4",400:"#2dd4bf",500:"#14b8a6",600:"#0d9488",700:"#0f766e",800:"#115e59",900:"#134e4a",950:"#042f2e"},cyan:{50:"#ecfeff",100:"#cffafe",200:"#a5f3fc",300:"#67e8f9",400:"#22d3ee",500:"#06b6d4",600:"#0891b2",700:"#0e7490",800:"#155e75",900:"#164e63",950:"#083344"},sky:{50:"#f0f9ff",100:"#e0f2fe",200:"#bae6fd",300:"#7dd3fc",400:"#38bdf8",500:"#0ea5e9",600:"#0284c7",700:"#0369a1",800:"#075985",900:"#0c4a6e",950:"#082f49"},blue:{50:"#eff6ff",100:"#dbeafe",200:"#bfdbfe",300:"#93c5fd",400:"#60a5fa",500:"#3b82f6",600:"#2563eb",700:"#1d4ed8",800:"#1e40af",900:"#1e3a8a",950:"#172554"},indigo:{50:"#eef2ff",100:"#e0e7ff",200:"#c7d2fe",300:"#a5b4fc",400:"#818cf8",500:"#6366f1",600:"#4f46e5",700:"#4338ca",800:"#3730a3",900:"#312e81",950:"#1e1b4b"},violet:{50:"#f5f3ff",100:"#ede9fe",200:"#ddd6fe",300:"#c4b5fd",400:"#a78bfa",500:"#8b5cf6",600:"#7c3aed",700:"#6d28d9",800:"#5b21b6",900:"#4c1d95",950:"#2e1065"},purple:{50:"#faf5ff",100:"#f3e8ff",200:"#e9d5ff",300:"#d8b4fe",400:"#c084fc",500:"#a855f7",600:"#9333ea",700:"#7e22ce",800:"#6b21a8",900:"#581c87",950:"#3b0764"},fuchsia:{50:"#fdf4ff",100:"#fae8ff",200:"#f5d0fe",300:"#f0abfc",400:"#e879f9",500:"#d946ef",600:"#c026d3",700:"#a21caf",800:"#86198f",900:"#701a75",950:"#4a044e"},pink:{50:"#fdf2f8",100:"#fce7f3",200:"#fbcfe8",300:"#f9a8d4",400:"#f472b6",500:"#ec4899",600:"#db2777",700:"#be185d",800:"#9d174d",900:"#831843",950:"#500724"},rose:{50:"#fff1f2",100:"#ffe4e6",200:"#fecdd3",300:"#fda4af",400:"#fb7185",500:"#f43f5e",600:"#e11d48",700:"#be123c",800:"#9f1239",900:"#881337",950:"#4c0519"}},ea=No.reduce((e,{color:t,primary:n,secondary:r})=>({...e,[t]:{primary:rn$2[t][n],secondary:rn$2[t][r]}}),{});function Gn(e){if(e==null)return "";const t=String(e),n=get_store_value(xt$2);let r=n(t);if(r!==t)return r;const i=t.toLowerCase();for(const o of Do){const s=o.substring(o.indexOf(".")+1);if(i===s){const a=n(o);if(a!==o)return a;break}}return t}const ta=derived(xt$2,()=>Gn),on$2={ar:"جاري التحميل",ca:"S'està carregant",ckb:"بارکردن",de:"Laden",en:"Loading",es:"Cargando",eu:"Kargatzen",fa:"در حال بارگذاری",fi:"Ladataan",fr:"Chargement",he:"טוען",hi:"लोड हो रहा है",ja:"読み込み中",ko:"로딩 중",lt:"Kraunama",nb:"Laster",nl:"Laden",pl:"Ładowanie","pt-BR":"Carregando",pt:"A carregar",ro:"Se încarcă",ru:"Загрузка",sv:"Laddar",ta:"ஏற்றுகிறது",th:"กำลังโหลด",tr:"Yükleniyor",uk:"Завантаження",ur:"لوڈ ہو رہا ہے",uz:"Yuklanmoqda","zh-CN":"加载中","zh-TW":"載入中"},Fn="English",zn$1={annotated_image:"Annotated Image"},$n={allow_recording_access:"Please allow access to the microphone for recording.",audio:"Audio",drop_to_upload:"Drop an audio file here to upload",record_from_microphone:"Record from microphone",stop_recording:"Stop recording",no_device_support:"Media devices could not be accessed. Check that you are running on a secure origin (https) or localhost (or you have passed a valid SSL certificate to ssl_verify), and you have allowed browser access to your device.",stop:"Stop",resume:"Resume",record:"Record",no_microphone:"No microphone found",pause:"Pause",play:"Play",waiting:"Waiting"},Wn={connection_can_break:"On mobile, the connection can break if this tab is unfocused or the device sleeps, losing your position in queue.",long_requests_queue:"There is a long queue of requests pending. Duplicate this Space to skip.",lost_connection:"Lost connection due to leaving page. Rejoining queue...",waiting_for_inputs:"Waiting for file(s) to finish uploading, please retry."},Vn={edit:"Edit",retry:"Retry",undo:"Undo",submit:"Submit",cancel:"Cancel",like:"Like",dislike:"Dislike",clear:"Clear"},qn={checkbox:"Checkbox",checkbox_group:"Checkbox Group"},Qn={code:"Code"},Xn={color_picker:"Color Picker"},Kn={built_with:"built with",built_with_gradio:"Built with Gradio",clear:"Clear",download:"Download",edit:"Edit",empty:"Empty",error:"Error",hosted_on:"Hosted on",loading:"Loading",logo:"logo",or:"or",remove:"Remove",settings:"Settings",share:"Share",submit:"Submit",undo:"Undo",no_devices:"No devices found",language:"Language",display_theme:"Display Theme",pwa:"Progressive Web App",record:"Record",stop_recording:"Stop Recording",screen_studio:"Screen Studio",share_gradio_tab:"[Sharing] Gradio Tab",run:"Run"},Zn={incorrect_format:"Incorrect format, only CSV and TSV files are supported",new_column:"Add column",new_row:"New row",add_row_above:"Add row above",add_row_below:"Add row below",delete_row:"Delete row",delete_column:"Delete column",add_column_left:"Add column to the left",add_column_right:"Add column to the right",sort_column:"Sort column",sort_ascending:"Sort ascending",sort_descending:"Sort descending",drop_to_upload:"Drop CSV or TSV files here to import data into dataframe",clear_sort:"Clear sort",filter:"Filter",clear_filter:"Clear filters"},Yn={dropdown:"Dropdown"},Jn={build_error:"there is a build error",config_error:"there is a config error",contact_page_author:"Please contact the author of the page to let them know.",no_app_file:"there is no app file",runtime_error:"there is a runtime error",space_not_working:`"Space isn't working because" {0}`,space_paused:"the space is paused",use_via_api:"Use via API",use_via_api_or_mcp:"Use via API or MCP"},er$1={uploading:"Uploading..."},tr$1={highlighted_text:"Highlighted Text"},nr$1={allow_webcam_access:"Please allow access to the webcam for recording.",brush_color:"Brush color",brush_radius:"Brush radius",image:"Image",remove_image:"Remove Image",select_brush_color:"Select brush color",start_drawing:"Start drawing",use_brush:"Use brush",drop_to_upload:"Drop an image file here to upload"},rr$1={label:"Label"},ir$1={enable_cookies:"If you are visiting a HuggingFace Space in Incognito mode, you must enable third party cookies.",incorrect_credentials:"Incorrect Credentials",username:"username",password:"password",login:"Login"},or$1={number:"Number"},sr$1={plot:"Plot"},ar$1={radio:"Radio"},lr$1={slider:"Slider"},cr$1={click_to_upload:"Click to Upload",drop_audio:"Drop Audio Here",drop_csv:"Drop CSV Here",drop_file:"Drop File Here",drop_image:"Drop Image Here",drop_video:"Drop Video Here",drop_gallery:"Drop Media Here",paste_clipboard:"Paste from Clipboard"},ur$1={drop_to_upload:"Drop a video file here to upload"},Bt$1={_name:Fn,"3D_model":{"3d_model":"3D Model",drop_to_upload:"Drop a 3D model (.obj, .glb, .stl, .gltf, .splat, or .ply) file here to upload"},annotated_image:zn$1,audio:$n,blocks:Wn,chatbot:Vn,checkbox:qn,code:Qn,color_picker:Xn,common:Kn,dataframe:Zn,dropdown:Yn,errors:Jn,file:er$1,highlighted_text:tr$1,image:nr$1,label:rr$1,login:ir$1,number:or$1,plot:sr$1,radio:ar$1,slider:lr$1,upload_text:cr$1,video:ur$1},Mo=Object.freeze(Object.defineProperty({__proto__:null,_name:Fn,annotated_image:zn$1,audio:$n,blocks:Wn,chatbot:Vn,checkbox:qn,code:Qn,color_picker:Xn,common:Kn,dataframe:Zn,default:Bt$1,dropdown:Yn,errors:Jn,file:er$1,highlighted_text:tr$1,image:nr$1,label:rr$1,login:ir$1,number:or$1,plot:sr$1,radio:ar$1,slider:lr$1,upload_text:cr$1,video:ur$1},Symbol.toStringTag,{value:"Module"})),Lo={ar:"العربية",ca:"Català",ckb:"کوردی",de:"Deutsch",en:"English",es:"Español",eu:"Euskara",fa:"فارسی",fi:"Suomi",fr:"Français",he:"עברית",hi:"हिंदी",ja:"日本語",ko:"한국어",lt:"Lietuvių",nb:"Norsk bokmål",nl:"Nederlands",pl:"Polski","pt-BR":"Português do Brasil",pt:"Português",ro:"Română",ru:"Русский",sv:"Svenska",ta:"தமிழ்",th:"ภาษาไทย",tr:"Türkçe",uk:"Українська",ur:"اردو",uz:"O'zbek","zh-CN":"简体中文","zh-TW":"繁體中文"},Ro=Object.assign({"./lang/ar.json":()=>import('./ar-CuuB9Ohn.js'),"./lang/ca.json":()=>import('./ca-BvH50zSS.js'),"./lang/ckb.json":()=>import('./ckb-l7nR8ql7.js'),"./lang/de.json":()=>import('./de-B1wU7-Ch.js'),"./lang/en.json":()=>Promise.resolve().then(()=>Mo),"./lang/es.json":()=>import('./es-B2LmZtQQ.js'),"./lang/eu.json":()=>import('./eu-DQN2mBJJ.js'),"./lang/fa.json":()=>import('./fa-DJTEw8mO.js'),"./lang/fi.json":()=>import('./fi-BJkPVS_L.js'),"./lang/fr.json":()=>import('./fr-Doonyoep.js'),"./lang/he.json":()=>import('./he-C5xAKd5S.js'),"./lang/hi.json":()=>import('./hi-DKgm37B9.js'),"./lang/ja.json":()=>import('./ja-IeX0ScdE.js'),"./lang/ko.json":()=>import('./ko-CWBcxRwV.js'),"./lang/lt.json":()=>import('./lt-DuVbsrrG.js'),"./lang/nb.json":()=>import('./nb-D08346Tf.js'),"./lang/nl.json":()=>import('./nl-C9vqu2l6.js'),"./lang/pl.json":()=>import('./pl-CCZ3iBe5.js'),"./lang/pt-BR.json":()=>import('./pt-BR-DPuva9n4.js'),"./lang/pt.json":()=>import('./pt-B_nt5bpZ.js'),"./lang/ro.json":()=>import('./ro-Ddw_SWeO.js'),"./lang/ru.json":()=>import('./ru-hxtnGKGc.js'),"./lang/sv.json":()=>import('./sv-CBaAzwhi.js'),"./lang/ta.json":()=>import('./ta-CIRcMeU1.js'),"./lang/th.json":()=>import('./th-CWKCe4yc.js'),"./lang/tr.json":()=>import('./tr-BjNdPtGX.js'),"./lang/uk.json":()=>import('./uk-DxkC9TjY.js'),"./lang/ur.json":()=>import('./ur-DPrEFG9j.js'),"./lang/uz.json":()=>import('./uz-BUySSN8V.js'),"./lang/zh-CN.json":()=>import('./zh-CN-CPutFXEq.js'),"./lang/zh-TW.json":()=>import('./zh-TW-CFo1-iyM.js')});function na(e){return e&&typeof e=="object"&&e.__type__==="translation_metadata"&&typeof e.key=="string"}function ra(e){if(typeof e!="string")return e;const t="__i18n__",n=e.indexOf(t);if(n===-1)return e;try{const r=n>0?e.substring(0,n):"",i=n+t.length,o=e.indexOf("{",i);let s=-1,a=0;for(let l=o;l<e.length;l++)if(e[l]==="{"&&a++,e[l]==="}"&&a--,a===0){s=l+1;break}if(s===-1)return console.error("Could not find end of JSON in i18n string"),e;const u=e.substring(o,s),c=s<e.length?e.substring(s):"";try{const l=JSON.parse(u);if(l&&l.key){const f=Gn(l.key);return r+f+c}}catch(l){console.error("Error parsing i18n JSON:",l);}return e}catch(r){return console.error("Error processing translation:",r),e}}function ko(){return {...Object.fromEntries(Object.entries(Ro).map(([t,n])=>[t.split("/").pop().split(".")[0],{type:"lazy",data:n}])),en:{type:"static",data:Bt$1}}}const It$1=ko(),sn$2=Object.keys(It$1),ia=Object.entries(It$1).map(([e])=>[Lo[e]||e,e]);let Do=new Set,at$3=!1,an$2;async function oa(e){if(at$3&&!(at$3&&e!==an$2))return;an$2=e,Uo({processed_langs:It$1,custom_translations:e??{}});const n=ao();let r=n&&sn$2.includes(n)?n:null;if(!r){const i=n?.split("-")[0];r=i&&sn$2.includes(i)?i:"en";}await Yi({fallbackLocale:"en",initialLocale:r}),at$3=!0;}function sa(e){_e$1.set(e);}function aa(e,t,n="en"){return e&&t.includes(e)?e:n}function Uo(e){if(e){try{for(const t in e.custom_translations)Ge$1(t,e.custom_translations[t]);for(const t in e.processed_langs)t==="en"&&e.processed_langs[t].type==="static"?Ge$1(t,Bt$1):e.processed_langs[t].type==="lazy"&&Wi(t,e.processed_langs[t].data);}catch(t){console.error("Error loading translations:",t);}for(const t in on$2)Ge$1(t,{common:{loading:on$2[t]}});}}var lt$4=new Intl.Collator(0,{numeric:1}).compare;function fr$1(e,t,n){return e=e.split("."),t=t.split("."),lt$4(e[0],t[0])||lt$4(e[1],t[1])||(t[2]=t.slice(2).join("."),n=/[.-]/.test(e[2]=e.slice(2).join(".")),n==/[.-]/.test(t[2])?lt$4(e[2],t[2]):n?-1:1)}const jo="host",hr$1="queue/data",Go="queue/join",ln$2="upload",Fo="login",cn$2="config",zo="info",$o="runtime",Wo="sleeptime",Vo="heartbeat",qo="component_server",Qo="reset",Xo="cancel",Ko="app_id",Zo="https://gradio-space-api-fetcher-v2.hf.space/api",pr$1="This application is currently busy. Please try again. ",me$2="Connection errored out. ",ce$2="Could not resolve app config. ",Yo="Could not get space status. ",Jo="Could not get API info. ",Tt$2="Space metadata could not be loaded. ",es="Invalid URL. A full URL path is required.",ts="Not authorized to access this space. ",dr$1="Invalid credentials. Could not login. ",ns="Login credentials are required to access this space.",rs="File system access is only available in Node.js environments",mr$1="Root URL not found in client config",is="Error uploading file";function os(e,t,n){return t.startsWith("http://")||t.startsWith("https://")?n?e:t:e+t}async function un$2(e,t,n){try{return (await(await fetch(`https://huggingface.co/api/spaces/${e}/jwt`,{headers:{Authorization:`Bearer ${t}`,...n?{Cookie:n}:{}}})).json()).token||!1}catch{return !1}}function ss(e){let t={};return e.forEach(({api_name:n,id:r})=>{n&&(t[n]=r);}),t}async function as(e){const t=this.options.hf_token?{Authorization:`Bearer ${this.options.hf_token}`}:{};if(t["Content-Type"]="application/json",typeof window<"u"&&window.gradio_config&&location.origin!=="http://localhost:9876"&&!window.gradio_config.dev_mode)return window.gradio_config.current_page&&(e=e.substring(0,e.lastIndexOf("/"))),window.gradio_config.root=e,{...window.gradio_config};if(e){let n=gr$1(e,this.deep_link?cn$2+"?deep_link="+this.deep_link:cn$2);const r=await this.fetch(n,{headers:t,credentials:"include"});return ls(r,e,!!this.options.auth)}throw new Error(ce$2)}async function ls(e,t,n){if(e?.status===401&&!n){const i=(await e.json())?.detail?.auth_message;throw new Error(i||ns)}else if(e?.status===401&&n)throw new Error(dr$1);if(e?.status===200){let r=await e.json();return r.root=t,r.dependencies?.forEach((i,o)=>{i.id===void 0&&(i.id=o);}),r}else if(e?.status===401)throw new Error(ts);throw new Error(ce$2)}async function cs(){const{http_protocol:e,host:t}=await Xe$1(this.app_reference,this.options.hf_token);try{if(this.options.auth){const n=await Ar$1(e,t,this.options.auth,this.fetch,this.options.hf_token);n&&this.set_cookies(n);}}catch(n){throw Error(n.message)}}async function Ar$1(e,t,n,r,i){const o=new FormData;o.append("username",n?.[0]),o.append("password",n?.[1]);let s={};i&&(s.Authorization=`Bearer ${i}`);const a=await r(`${e}//${t}/${Fo}`,{headers:s,method:"POST",body:o,credentials:"include"});if(a.status===200)return a.headers.get("set-cookie");throw a.status===401?new Error(dr$1):new Error(Tt$2)}function ct$3(e){if(e.startsWith("http")){const{protocol:t,host:n,pathname:r}=new URL(e);return {ws_protocol:t==="https:"?"wss":"ws",http_protocol:t,host:n+(r!=="/"?r:"")}}else if(e.startsWith("file:"))return {ws_protocol:"ws",http_protocol:"http:",host:"lite.local"};return {ws_protocol:"wss",http_protocol:"https:",host:new URL(e).host}}const _r$1=e=>{let t=[];return e.split(/,(?=\s*[^\s=;]+=[^\s=;]+)/).forEach(r=>{const[i,o]=r.split(";")[0].split("=");i&&o&&t.push(`${i.trim()}=${o.trim()}`);}),t},Ot$1=/^[a-zA-Z0-9_\-\.]+\/[a-zA-Z0-9_\-\.]+$/,us=/.*hf\.space\/{0,1}.*$/;async function Xe$1(e,t){const n={};t&&(n.Authorization=`Bearer ${t}`);const r=e.trim().replace(/\/$/,"");if(Ot$1.test(r))try{const o=(await(await fetch(`https://huggingface.co/api/spaces/${r}/${jo}`,{headers:n})).json()).host;return {space_id:e,...ct$3(o)}}catch{throw new Error(Tt$2)}if(us.test(r)){const{ws_protocol:i,http_protocol:o,host:s}=ct$3(r);return {space_id:s.split("/")[0].replace(".hf.space",""),ws_protocol:i,http_protocol:o,host:s}}return {space_id:!1,...ct$3(r)}}const gr$1=(...e)=>{try{return e.reduce((t,n)=>(t=t.replace(/\/+$/,""),n=n.replace(/^\/+/,""),new URL(n,t+"/").toString()))}catch{throw new Error(es)}};function fs(e,t,n){const r={named_endpoints:{},unnamed_endpoints:{}};return Object.keys(e).forEach(i=>{(i==="named_endpoints"||i==="unnamed_endpoints")&&(r[i]={},Object.entries(e[i]).forEach(([o,{parameters:s,returns:a}])=>{const u=t.dependencies.find(f=>f.api_name===o||f.api_name===o.replace("/",""))?.id||n[o.replace("/","")]||-1,c=u!==-1?t.dependencies.find(f=>f.id==u)?.types:{generator:!1,cancel:!1};if(u!==-1&&t.dependencies.find(f=>f.id==u)?.inputs?.length!==s.length){const f=t.dependencies.find(h=>h.id==u).inputs.map(h=>t.components.find(_=>_.id===h)?.type);try{f.forEach((h,_)=>{if(h==="state"){const m={component:"state",example:null,parameter_default:null,parameter_has_default:!0,parameter_name:null,hidden:!0};s.splice(_,0,m);}});}catch(h){console.error(h);}}const l=(f,h,_,m)=>({...f,description:ps(f?.type,_),type:hs(f?.type,h,_,m)||""});r[i][o]={parameters:s.map(f=>l(f,f?.component,f?.serializer,"parameter")),returns:a.map(f=>l(f,f?.component,f?.serializer,"return")),type:c};}));}),r}function hs(e,t,n,r){if(t==="Api")return e.type;switch(e?.type){case"string":return "string";case"boolean":return "boolean";case"number":return "number"}if(n==="JSONSerializable"||n==="StringSerializable")return "any";if(n==="ListStringSerializable")return "string[]";if(t==="Image")return r==="parameter"?"Blob | File | Buffer":"string";if(n==="FileSerializable")return e?.type==="array"?r==="parameter"?"(Blob | File | Buffer)[]":"{ name: string; data: string; size?: number; is_file?: boolean; orig_name?: string}[]":r==="parameter"?"Blob | File | Buffer":"{ name: string; data: string; size?: number; is_file?: boolean; orig_name?: string}";if(n==="GallerySerializable")return r==="parameter"?"[(Blob | File | Buffer), (string | null)][]":"[{ name: string; data: string; size?: number; is_file?: boolean; orig_name?: string}, (string | null))][]"}function ps(e,t){return t==="GallerySerializable"?"array of [file, label] tuples":t==="ListStringSerializable"?"array of strings":t==="FileSerializable"?"array of files or single file":e?.description}function ut$1(e,t){switch(e.msg){case"send_data":return {type:"data"};case"send_hash":return {type:"hash"};case"queue_full":return {type:"update",status:{queue:!0,message:pr$1,stage:"error",code:e.code,success:e.success}};case"heartbeat":return {type:"heartbeat"};case"unexpected_error":return {type:"unexpected_error",status:{queue:!0,message:e.message,session_not_found:e.session_not_found,stage:"error",success:!1}};case"broken_connection":return {type:"broken_connection",status:{queue:!0,message:e.message,stage:"error",success:!1}};case"estimation":return {type:"update",status:{queue:!0,stage:t||"pending",code:e.code,size:e.queue_size,position:e.rank,eta:e.rank_eta,success:e.success}};case"progress":return {type:"update",status:{queue:!0,stage:"pending",code:e.code,progress_data:e.progress_data,success:e.success}};case"log":return {type:"log",data:e};case"process_generating":return {type:"generating",status:{queue:!0,message:e.success?null:e.output.error,stage:e.success?"generating":"error",code:e.code,progress_data:e.progress_data,eta:e.average_duration,changed_state_ids:e.success?e.output.changed_state_ids:void 0},data:e.success?e.output:null};case"process_streaming":return {type:"streaming",status:{queue:!0,message:e.output.error,stage:"streaming",time_limit:e.time_limit,code:e.code,progress_data:e.progress_data,eta:e.eta},data:e.output};case"process_completed":return "error"in e.output?{type:"update",status:{queue:!0,title:e.output.title,message:e.output.error,visible:e.output.visible,duration:e.output.duration,stage:"error",code:e.code,success:e.success}}:{type:"complete",status:{queue:!0,message:e.success?void 0:e.output.error,stage:e.success?"complete":"error",code:e.code,progress_data:e.progress_data,changed_state_ids:e.success?e.output.changed_state_ids:void 0},data:e.success?e.output:null};case"process_starts":return {type:"update",status:{queue:!0,stage:"pending",code:e.code,size:e.rank,position:0,success:e.success,eta:e.eta},original_msg:"process_starts"}}return {type:"none",status:{stage:"error",queue:!0}}}const ds=(e=[],t)=>{const n=t?t.parameters:[];if(Array.isArray(e))return t&&n.length>0&&e.length>n.length&&console.warn("Too many arguments provided for the endpoint."),e;const r=[],i=Object.keys(e);return n.forEach((o,s)=>{if(e.hasOwnProperty(o.parameter_name))r[s]=e[o.parameter_name];else if(o.parameter_has_default)r[s]=o.parameter_default;else throw new Error(`No value provided for required parameter: ${o.parameter_name}`)}),i.forEach(o=>{if(!n.some(s=>s.parameter_name===o))throw new Error(`Parameter \`${o}\` is not a valid keyword argument. Please refer to the API for usage.`)}),r.forEach((o,s)=>{if(o===void 0&&!n[s].parameter_has_default)throw new Error(`No value provided for required parameter: ${n[s].parameter_name}`)}),r};async function ms(){if(this.api_info)return this.api_info;const{hf_token:e}=this.options,{config:t}=this,n={"Content-Type":"application/json"};if(e&&(n.Authorization=`Bearer ${e}`),!!t)try{let r,i;if(typeof window<"u"&&window.gradio_api_info)i=window.gradio_api_info;else {if(fr$1(t?.version||"2.0.0","3.30")<0)r=await this.fetch(Zo,{method:"POST",body:JSON.stringify({serialize:!1,config:JSON.stringify(t)}),headers:n,credentials:"include"});else {const o=gr$1(t.root,this.api_prefix,zo);r=await this.fetch(o,{headers:n,credentials:"include"});}if(!r.ok)throw new Error(me$2);i=await r.json();}return "api"in i&&(i=i.api),i.named_endpoints["/predict"]&&!i.unnamed_endpoints[0]&&(i.unnamed_endpoints[0]=i.named_endpoints["/predict"]),fs(i,t,this.api_map)}catch(r){throw new Error("Could not get API info. "+r.message)}}async function As(e,t,n){const r={};this?.options?.hf_token&&(r.Authorization=`Bearer ${this.options.hf_token}`);const i=1e3,o=[];let s;for(let a=0;a<t.length;a+=i){const u=t.slice(a,a+i),c=new FormData;u.forEach(f=>{c.append("files",f);});try{const f=n?`${e}${this.api_prefix}/${ln$2}?upload_id=${n}`:`${e}${this.api_prefix}/${ln$2}`;s=await this.fetch(f,{method:"POST",body:c,headers:r,credentials:"include"});}catch(f){throw new Error(me$2+f.message)}if(!s.ok){const f=await s.text();return {error:`HTTP ${s.status}: ${f}`}}const l=await s.json();l&&o.push(...l);}return {files:o}}async function _s(e,t,n,r){let i=(Array.isArray(e)?e:[e]).map(s=>s.blob);const o=i.filter(s=>s.size>(r??1/0));if(o.length)throw new Error(`File size exceeds the maximum allowed size of ${r} bytes: ${o.map(s=>s.name).join(", ")}`);return await Promise.all(await this.upload_files(t,i,n).then(async s=>{if(s.error)throw new Error(s.error);return s.files?s.files.map((a,u)=>new Ke$2({...e[u],path:a,url:`${t}${this.api_prefix}/file=${a}`})):[]}))}async function la(e,t){return e.map(n=>new Ke$2({path:n.name,orig_name:n.name,blob:n,size:n.size,mime_type:n.type,is_stream:t}))}let Ke$2 = class Ke{path;url;orig_name;size;blob;is_stream;mime_type;alt_text;b64;meta={_type:"gradio.FileData"};constructor({path:t,url:n,orig_name:r,size:i,blob:o,is_stream:s,mime_type:a,alt_text:u,b64:c}){this.path=t,this.url=n,this.orig_name=r,this.size=i,this.blob=n?void 0:o,this.is_stream=s,this.mime_type=a,this.alt_text=u,this.b64=c;}};class gs{type;command;meta;fileData;constructor(t,n){this.type="command",this.command=t,this.meta=n;}}typeof process<"u"&&process.versions&&process.versions.node;function fn$1(e,t,n){for(;n.length>1;){const i=n.shift();if(typeof i=="string"||typeof i=="number")e=e[i];else throw new Error("Invalid key type")}const r=n.shift();if(typeof r=="string"||typeof r=="number")e[r]=t;else throw new Error("Invalid key type")}async function vt$3(e,t=void 0,n=[],r=!1,i=void 0){if(Array.isArray(e)){let o=[];return await Promise.all(e.map(async(s,a)=>{let u=n.slice();u.push(String(a));const c=await vt$3(e[a],r?i?.parameters[a]?.component||void 0:t,u,!1,i);o=o.concat(c);})),o}else {if(globalThis.Buffer&&e instanceof globalThis.Buffer||e instanceof Blob)return [{path:n,blob:new Blob([e]),type:t}];if(typeof e=="object"&&e!==null){let o=[];for(const s of Object.keys(e)){const a=[...n,s],u=e[s];o=o.concat(await vt$3(u,void 0,a,!1,i));}return o}}return []}function bs(e,t){let n=t?.dependencies?.find(r=>r.id==e)?.queue;return n!=null?!n:!t.enable_queue}function vs(e,t){return new Promise((n,r)=>{const i=new MessageChannel;i.port1.onmessage=({data:o})=>{i.port1.close(),n(o);},window.parent.postMessage(e,t,[i.port2]);})}function Te$1(e,t,n,r,i=!1){if(r==="input"&&!i)throw new Error("Invalid code path. Cannot skip state inputs for input.");if(r==="output"&&i)return e;let o=[],s=0;const a=r==="input"?t.inputs:t.outputs;for(let u=0;u<a.length;u++){const c=a[u];if(n.find(f=>f.id===c)?.type==="state"){if(i)if(e.length===a.length){const f=e[s];o.push(f),s++;}else o.push(null);else {s++;continue}continue}else {const f=e[s];o.push(f),s++;}}return o}async function ys(e,t,n){const r=this;await ws(r,t);const i=await vt$3(t,void 0,[],!0,n);return (await Promise.all(i.map(async({path:s,blob:a,type:u})=>{if(!a)return {path:s,type:u};const c=await r.upload_files(e,[a]),l=c.files&&c.files[0];return {path:s,file_url:l,type:u,name:typeof File<"u"&&a instanceof File?a?.name:void 0}}))).forEach(({path:s,file_url:a,type:u,name:c})=>{if(u==="Gallery")fn$1(t,a,s);else if(a){const l=new Ke$2({path:a,orig_name:c});fn$1(t,l,s);}}),t}async function ws(e,t){if(!(e.config?.root||e.config?.root_url))throw new Error(mr$1);await br$1(e,t);}async function br$1(e,t,n=[]){for(const r in t)t[r]instanceof gs?await Cs(e,t,r):typeof t[r]=="object"&&t[r]!==null&&await br$1(e,t[r],[...n,r]);}async function Cs(e,t,n){let r=t[n];const i=e.config?.root||e.config?.root_url;if(!i)throw new Error(mr$1);try{let o,s;if(typeof process<"u"&&process.versions&&process.versions.node){const l=await import('fs/promises');s=(await import('path')).resolve(process.cwd(),r.meta.path),o=await l.readFile(s);}else throw new Error(rs);const a=new Blob([o],{type:"application/octet-stream"}),u=await e.upload_files(i,[a]),c=u.files&&u.files[0];if(c){const l=new Ke$2({path:c,orig_name:r.meta.name||""});t[n]=l;}}catch(o){console.error(is,o);}}async function Es(e,t,n){const r={"Content-Type":"application/json"};this.options.hf_token&&(r.Authorization=`Bearer ${this.options.hf_token}`);try{var i=await this.fetch(e,{method:"POST",body:JSON.stringify(t),headers:{...r,...n},credentials:"include"});}catch{return [{error:me$2},500]}let o,s;try{o=await i.json(),s=i.status;}catch(a){o={error:`Could not parse server response: ${a}`},s=500;}return [o,s]}async function xs(e,t={}){let n=!1,r=!1;if(!this.config)throw new Error("Could not resolve app config");if(typeof e=="number")this.config.dependencies.find(i=>i.id==e);else {const i=e.replace(/^\//,"");this.config.dependencies.find(o=>o.id==this.api_map[i]);}return new Promise(async(i,o)=>{const s=this.submit(e,t,null,null,!0);let a;for await(const u of s)u.type==="data"&&(r&&i(a),n=!0,a=u),u.type==="status"&&(u.stage==="error"&&o(u),u.stage==="complete"&&(r=!0,n&&i(a)));})}async function Me$1(e,t,n){let r=t==="subdomain"?`https://huggingface.co/api/spaces/by-subdomain/${e}`:`https://huggingface.co/api/spaces/${e}`,i,o;try{if(i=await fetch(r),o=i.status,o!==200)throw new Error;i=await i.json();}catch{n({status:"error",load_status:"error",message:Yo,detail:"NOT_FOUND"});return}if(!i||o!==200)return;const{runtime:{stage:s},id:a}=i;switch(s){case"STOPPED":case"SLEEPING":n({status:"sleeping",load_status:"pending",message:"Space is asleep. Waking it up...",detail:s}),setTimeout(()=>{Me$1(e,t,n);},1e3);break;case"PAUSED":n({status:"paused",load_status:"error",message:"This space has been paused by the author. If you would like to try this demo, consider duplicating the space.",detail:s,discussions_enabled:await hn$1(a)});break;case"RUNNING":case"RUNNING_BUILDING":n({status:"running",load_status:"complete",message:"Space is running.",detail:s});break;case"BUILDING":n({status:"building",load_status:"pending",message:"Space is building...",detail:s}),setTimeout(()=>{Me$1(e,t,n);},1e3);break;case"APP_STARTING":n({status:"starting",load_status:"pending",message:"Space is starting...",detail:s}),setTimeout(()=>{Me$1(e,t,n);},1e3);break;default:n({status:"space_error",load_status:"error",message:"This space is experiencing an issue.",detail:s,discussions_enabled:await hn$1(a)});break}}const vr$1=async(e,t)=>{let n=0;const r=12,i=5e3;return new Promise(o=>{Me$1(e,Ot$1.test(e)?"space_name":"subdomain",s=>{t(s),s.status==="running"||s.status==="error"||s.status==="paused"||s.status==="space_error"?o():(s.status==="sleeping"||s.status==="building")&&(n<r?(n++,setTimeout(()=>{vr$1(e,t).then(o);},i)):o());});})},Ss=/^(?=[^]*\b[dD]iscussions{0,1}\b)(?=[^]*\b[dD]isabled\b)[^]*$/;async function hn$1(e){try{const t=await fetch(`https://huggingface.co/api/spaces/${e}/discussions`,{method:"HEAD"}),n=t.headers.get("x-error-message");return !(!t.ok||n&&Ss.test(n))}catch{return !1}}async function Bs(e,t){const n={};t&&(n.Authorization=`Bearer ${t}`);try{const r=await fetch(`https://huggingface.co/api/spaces/${e}/${$o}`,{headers:n});if(r.status!==200)throw new Error("Space hardware could not be obtained.");const{hardware:i}=await r.json();return i.current}catch(r){throw new Error(r.message)}}async function Is(e,t,n){const r={};n&&(r.Authorization=`Bearer ${n}`);const i={seconds:t};try{const o=await fetch(`https://huggingface.co/api/spaces/${e}/${Wo}`,{method:"POST",headers:{"Content-Type":"application/json",...r},body:JSON.stringify(i)});if(o.status!==200)throw new Error("Could not set sleep timeout on duplicated Space. Please visit *ADD HF LINK TO SETTINGS* to set a timeout manually to reduce billing charges.");return await o.json()}catch(o){throw new Error(o.message)}}const pn$1=["cpu-basic","cpu-upgrade","cpu-xl","t4-small","t4-medium","a10g-small","a10g-large","a10g-largex2","a10g-largex4","a100-large","zero-a10g","h100","h100x8"];async function Ts(e,t){const{hf_token:n,private:r,hardware:i,timeout:o,auth:s}=t;if(i&&!pn$1.includes(i))throw new Error(`Invalid hardware type provided. Valid types are: ${pn$1.map(C=>`"${C}"`).join(",")}.`);const{http_protocol:a,host:u}=await Xe$1(e,n);let c=null;if(s){const C=await Ar$1(a,u,s,fetch);C&&(c=_r$1(C));}const l={Authorization:`Bearer ${n}`,"Content-Type":"application/json",...c?{Cookie:c.join("; ")}:{}},f=(await(await fetch("https://huggingface.co/api/whoami-v2",{headers:l})).json()).name,h=e.split("/")[1],_={repository:`${f}/${h}`};r&&(_.private=!0);let m;try{i||(m=await Bs(e,n));}catch(C){throw Error(Tt$2+C.message)}const B=i||m||"cpu-basic";_.hardware=B;try{const C=await fetch(`https://huggingface.co/api/spaces/${e}/duplicate`,{method:"POST",headers:l,body:JSON.stringify(_)});if(C.status===409)try{return await mn.connect(`${f}/${h}`,t)}catch(L){throw console.error("Failed to connect Client instance:",L),L}else if(C.status!==200)throw new Error(C.statusText);const k=await C.json();return await Is(`${f}/${h}`,o||300,n),await mn.connect(Os(k.url),t)}catch(C){throw new Error(C)}}function Os(e){const t=/https:\/\/huggingface.co\/spaces\/([^/]+\/[^/]+)/,n=e.match(t);if(n)return n[1]}class Hs extends TransformStream{#e="";constructor(t={allowCR:!1}){super({transform:(n,r)=>{for(n=this.#e+n;;){const i=n.indexOf(`
`),o=t.allowCR?n.indexOf("\r"):-1;if(o!==-1&&o!==n.length-1&&(i===-1||i-1>o)){r.enqueue(n.slice(0,o)),n=n.slice(o+1);continue}if(i===-1)break;const s=n[i-1]==="\r"?i-1:i;r.enqueue(n.slice(0,s)),n=n.slice(i+1);}this.#e=n;},flush:n=>{if(this.#e==="")return;const r=t.allowCR&&this.#e.endsWith("\r")?this.#e.slice(0,-1):this.#e;n.enqueue(r);}});}}function Ps(e){let t=new TextDecoderStream,n=new Hs({allowCR:!0});return e.pipeThrough(t).pipeThrough(n)}function Ns(e){let n=/[:]\s*/.exec(e),r=n&&n.index;if(r)return [e.substring(0,r),e.substring(r+n[0].length)]}function dn$2(e,t,n){e.get(t)||e.set(t,n);}async function*Ms(e,t){if(!e.body)return;let n=Ps(e.body),r,i=n.getReader(),o;for(;;){if(t&&t.aborted)return i.cancel();if(r=await i.read(),r.done)return;if(!r.value){o&&(yield o),o=void 0;continue}let[s,a]=Ns(r.value)||[];s&&(s==="data"?(o||={},o[s]=o[s]?o[s]+`
`+a:a):s==="event"?(o||={},o[s]=a):s==="id"?(o||={},o[s]=+a||a):s==="retry"&&(o||={},o[s]=+a||void 0));}}async function Ls(e,t){let n=new Request(e,t);dn$2(n.headers,"Accept","text/event-stream"),dn$2(n.headers,"Content-Type","application/json");let r=await fetch(n);if(!r.ok)throw r;return Ms(r,n.signal)}async function Rs(){let{event_callbacks:e,unclosed_events:t,pending_stream_messages:n,stream_status:r,config:i,jwt:o}=this;const s=this;if(!i)throw new Error("Could not resolve app config");r.open=!0;let a=null,u=new URLSearchParams({session_hash:this.session_hash}).toString(),c=new URL(`${i.root}${this.api_prefix}/${hr$1}?${u}`);if(o&&c.searchParams.set("__sign",o),a=this.stream(c),!a){console.warn("Cannot connect to SSE endpoint: "+c.toString());return}a.onmessage=async function(l){let f=JSON.parse(l.data);if(f.msg==="close_stream"){Ht(r,s.abort_controller);return}const h=f.event_id;if(!h)await Promise.all(Object.keys(e).map(_=>e[_](f)));else if(e[h]&&i){f.msg==="process_completed"&&["sse","sse_v1","sse_v2","sse_v2.1","sse_v3"].includes(i.protocol)&&t.delete(h);let _=e[h];typeof window<"u"&&typeof document<"u"?setTimeout(_,0,f):_(f);}else n[h]||(n[h]=[]),n[h].push(f);},a.onerror=async function(l){console.error(l),await Promise.all(Object.keys(e).map(f=>e[f]({msg:"broken_connection",message:me$2})));};}function Ht(e,t){e&&(e.open=!1,t?.abort());}function ks(e,t,n){!e[t]?(e[t]=[],n.data.forEach((i,o)=>{e[t][o]=i;})):n.data.forEach((i,o)=>{let s=Ds(e[t][o],i);e[t][o]=s,n.data[o]=s;});}function Ds(e,t){return t.forEach(([n,r,i])=>{e=Us(e,r,n,i);}),e}function Us(e,t,n,r){if(t.length===0){if(n==="replace")return r;if(n==="append")return e+r;throw new Error(`Unsupported action: ${n}`)}let i=e;for(let s=0;s<t.length-1;s++)i=i[t[s]];const o=t[t.length-1];switch(n){case"replace":i[o]=r;break;case"append":i[o]+=r;break;case"add":Array.isArray(i)?i.splice(Number(o),0,r):i[o]=r;break;case"delete":Array.isArray(i)?i.splice(Number(o),1):delete i[o];break;default:throw new Error(`Unknown action: ${n}`)}return e}function js(e,t={}){const n={close:()=>{console.warn("Method not implemented.");},onerror:null,onmessage:null,onopen:null,readyState:0,url:e.toString(),withCredentials:!1,CONNECTING:0,OPEN:1,CLOSED:2,addEventListener:()=>{throw new Error("Method not implemented.")},dispatchEvent:()=>{throw new Error("Method not implemented.")},removeEventListener:()=>{throw new Error("Method not implemented.")}};return Ls(e,t).then(async r=>{n.readyState=n.OPEN;try{for await(const i of r)n.onmessage&&n.onmessage(i);n.readyState=n.CLOSED;}catch(i){n.onerror&&n.onerror(i),n.readyState=n.CLOSED;}}).catch(r=>{console.error(r),n.onerror&&n.onerror(r),n.readyState=n.CLOSED;}),n}function Gs(e,t={},n,r,i){try{let o=function(H){(i||Z[H.type])&&c(H);},s=function(){for(Be=!0;ie.length>0;)ie.shift()({value:void 0,done:!0});},a=function(H){ie.length>0?ie.shift()(H):ae.push(H);},u=function(H){a(Fs(H)),s();},c=function(H){a({value:H,done:!1});},l=function(){return ae.length>0?Promise.resolve(ae.shift()):new Promise(H=>ie.push(H))};const{hf_token:f}=this.options,{fetch:h,app_reference:_,config:m,session_hash:B,api_info:C,api_map:k,stream_status:L,pending_stream_messages:N,pending_diff_streams:D,event_callbacks:j,unclosed_events:P,post_data:R,options:G,api_prefix:W}=this,ge=this;if(!C)throw new Error("No API found");if(!m)throw new Error("Could not resolve app config");let{fn_index:v,endpoint_info:be,dependency:K}=zs(C,e,k,m),Ze=ds(t,be),F,se,g=m.protocol??"ws",b="",E=()=>b;const p=typeof e=="number"?"/predict":e;let A,y=null,d=!1,T={},O=typeof window<"u"&&typeof document<"u"?new URLSearchParams(window.location.search).toString():"";const Z=G?.events?.reduce((H,oe)=>(H[oe]=!0,H),{})||{};async function Pt(){let H={},oe={};g==="ws"?(F&&F.readyState===0?F.addEventListener("open",()=>{F.close();}):F.close(),H={fn_index:v,session_hash:B}):(H={event_id:y},oe={event_id:y,session_hash:B,fn_index:v});try{if(!m)throw new Error("Could not resolve app config");"event_id"in oe&&await h(`${m.root}${W}/${Xo}`,{headers:{"Content-Type":"application/json"},method:"POST",body:JSON.stringify(oe)}),await h(`${m.root}${W}/${Qo}`,{headers:{"Content-Type":"application/json"},method:"POST",body:JSON.stringify(H)});}catch{console.warn("The `/reset` endpoint could not be called. Subsequent endpoint results may be unreliable.");}}const w=async H=>{await this._resolve_heartbeat(H);};async function V(H){if(!m)return;let oe=H.render_id;m.components=[...m.components.filter(q=>q.props.rendered_in!==oe),...H.components],m.dependencies=[...m.dependencies.filter(q=>q.rendered_in!==oe),...H.dependencies];const De=m.components.some(q=>q.type==="state"),U=m.dependencies.some(q=>q.targets.some(ne=>ne[1]==="unload"));m.connect_heartbeat=De||U,await w(m),o({type:"render",data:H,endpoint:p,fn_index:v});}this.handle_blob(m.root,Ze,be).then(async H=>{if(A={data:Te$1(H,K,m.components,"input",!0)||[],event_data:n,fn_index:v,trigger_id:r},bs(v,m))o({type:"status",endpoint:p,stage:"pending",queue:!1,fn_index:v,time:new Date}),R(`${m.root}${W}/run${p.startsWith("/")?p:`/${p}`}${O?"?"+O:""}`,{...A,session_hash:B}).then(([U,q])=>{const ne=U.data;q==200?(o({type:"data",endpoint:p,fn_index:v,data:Te$1(ne,K,m.components,"output",G.with_null_state),time:new Date,event_data:n,trigger_id:r}),U.render_config&&V(U.render_config),o({type:"status",endpoint:p,fn_index:v,stage:"complete",eta:U.average_duration,queue:!1,time:new Date})):o({type:"status",stage:"error",endpoint:p,fn_index:v,message:U.error,queue:!1,time:new Date});}).catch(U=>{o({type:"status",stage:"error",message:U.message,endpoint:p,fn_index:v,queue:!1,time:new Date});});else if(g=="ws"){const{ws_protocol:U,host:q}=await Xe$1(_,f);o({type:"status",stage:"pending",queue:!0,endpoint:p,fn_index:v,time:new Date});let ne=new URL(`${U}://${os(q,m.root,!0)}/queue/join${O?"?"+O:""}`);this.jwt&&ne.searchParams.set("__sign",this.jwt),F=new WebSocket(ne),F.onclose=Y=>{Y.wasClean||o({type:"status",stage:"error",broken:!0,message:me$2,queue:!0,endpoint:p,fn_index:v,time:new Date});},F.onmessage=function(Y){const re=JSON.parse(Y.data),{type:z,status:Q,data:X}=ut$1(re,T[v]);if(z==="update"&&Q&&!d)o({type:"status",endpoint:p,fn_index:v,time:new Date,...Q}),Q.stage==="error"&&F.close();else if(z==="hash"){F.send(JSON.stringify({fn_index:v,session_hash:B}));return}else z==="data"?F.send(JSON.stringify({...A,session_hash:B})):z==="complete"?d=Q:z==="log"?o({type:"log",title:X.title,log:X.log,level:X.level,endpoint:p,duration:X.duration,visible:X.visible,fn_index:v}):z==="generating"&&o({type:"status",time:new Date,...Q,stage:Q?.stage,queue:!0,endpoint:p,fn_index:v});X&&(o({type:"data",time:new Date,data:Te$1(X.data,K,m.components,"output",G.with_null_state),endpoint:p,fn_index:v,event_data:n,trigger_id:r}),d&&(o({type:"status",time:new Date,...d,stage:Q?.stage,queue:!0,endpoint:p,fn_index:v}),F.close()));},fr$1(m.version||"2.0.0","3.6")<0&&addEventListener("open",()=>F.send(JSON.stringify({hash:B})));}else if(g=="sse"){o({type:"status",stage:"pending",queue:!0,endpoint:p,fn_index:v,time:new Date});var De=new URLSearchParams({fn_index:v.toString(),session_hash:B}).toString();let U=new URL(`${m.root}${W}/${hr$1}?${O?O+"&":""}${De}`);if(this.jwt&&U.searchParams.set("__sign",this.jwt),se=this.stream(U),!se)return Promise.reject(new Error("Cannot connect to SSE endpoint: "+U.toString()));se.onmessage=async function(q){const ne=JSON.parse(q.data),{type:Y,status:re,data:z}=ut$1(ne,T[v]);if(Y==="update"&&re&&!d)o({type:"status",endpoint:p,fn_index:v,time:new Date,...re}),re.stage==="error"&&(se?.close(),s());else if(Y==="data"){let[Q,X]=await R(`${m.root}${W}/queue/data`,{...A,session_hash:B,event_id:y});X!==200&&(o({type:"status",stage:"error",message:me$2,queue:!0,endpoint:p,fn_index:v,time:new Date}),se?.close(),s());}else Y==="complete"?d=re:Y==="log"?o({type:"log",title:z.title,log:z.log,level:z.level,endpoint:p,duration:z.duration,visible:z.visible,fn_index:v}):(Y==="generating"||Y==="streaming")&&o({type:"status",time:new Date,...re,stage:re?.stage,queue:!0,endpoint:p,fn_index:v});z&&(o({type:"data",time:new Date,data:Te$1(z.data,K,m.components,"output",G.with_null_state),endpoint:p,fn_index:v,event_data:n,trigger_id:r}),d&&(o({type:"status",time:new Date,...d,stage:re?.stage,queue:!0,endpoint:p,fn_index:v}),se?.close(),s()));};}else if(g=="sse_v1"||g=="sse_v2"||g=="sse_v2.1"||g=="sse_v3"){o({type:"status",stage:"pending",queue:!0,endpoint:p,fn_index:v,time:new Date});let U="";typeof window<"u"&&typeof document<"u"&&(U=window?.location?.hostname);const ne=U.includes(".dev.")?`https://moon-${U.split(".")[1]}.dev.spaces.huggingface.tech`:"https://huggingface.co";(typeof window<"u"&&typeof document<"u"&&window.parent!=window&&window.supports_zerogpu_headers?vs("zerogpu-headers",ne):Promise.resolve(null)).then(Q=>R(`${m.root}${W}/${Go}?${O}`,{...A,session_hash:B},Q)).then(async([Q,X])=>{if(X===503)o({type:"status",stage:"error",message:pr$1,queue:!0,endpoint:p,fn_index:v,time:new Date});else if(X!==200)o({type:"status",stage:"error",broken:!0,message:me$2,queue:!0,endpoint:p,fn_index:v,time:new Date});else {y=Q.event_id,b=y;let Nt=async function(Ye){try{const{type:J,status:ee,data:te,original_msg:yr}=ut$1(Ye,T[v]);if(J=="heartbeat")return;if(J==="update"&&ee&&!d)o({type:"status",endpoint:p,fn_index:v,time:new Date,original_msg:yr,...ee});else if(J==="complete")d=ee;else if(J=="unexpected_error"||J=="broken_connection"){console.error("Unexpected error",ee?.message);const wr=J==="broken_connection";o({type:"status",stage:"error",message:ee?.message||"An Unexpected Error Occurred!",queue:!0,endpoint:p,broken:wr,session_not_found:ee?.session_not_found,fn_index:v,time:new Date});}else if(J==="log"){o({type:"log",title:te.title,log:te.log,level:te.level,endpoint:p,duration:te.duration,visible:te.visible,fn_index:v});return}else (J==="generating"||J==="streaming")&&(o({type:"status",time:new Date,...ee,stage:ee?.stage,queue:!0,endpoint:p,fn_index:v}),te&&K.connection!=="stream"&&["sse_v2","sse_v2.1","sse_v3"].includes(g)&&ks(D,y,te));te&&(o({type:"data",time:new Date,data:Te$1(te.data,K,m.components,"output",G.with_null_state),endpoint:p,fn_index:v}),te.render_config&&await V(te.render_config),d&&(o({type:"status",time:new Date,...d,stage:ee?.stage,queue:!0,endpoint:p,fn_index:v}),s())),(ee?.stage==="complete"||ee?.stage==="error")&&(j[y]&&delete j[y],y in D&&delete D[y]);}catch(J){console.error("Unexpected client exception",J),o({type:"status",stage:"error",message:"An Unexpected Error Occurred!",queue:!0,endpoint:p,fn_index:v,time:new Date}),["sse_v2","sse_v2.1","sse_v3"].includes(g)&&(Ht(L,ge.abort_controller),L.open=!1,s());}};y in N&&(N[y].forEach(Ye=>Nt(Ye)),delete N[y]),j[y]=Nt,P.add(y),L.open||await this.open_stream();}});}});let Be=!1;const ae=[],ie=[],ve={[Symbol.asyncIterator]:()=>ve,next:l,throw:async H=>(u(H),l()),return:async()=>(s(),l()),cancel:Pt,event_id:E};return ve}catch(o){throw console.error("Submit function encountered an error:",o),o}}function Fs(e){return {then:(t,n)=>n(e)}}function zs(e,t,n,r){let i,o,s;if(typeof t=="number")i=t,o=e.unnamed_endpoints[i],s=r.dependencies.find(a=>a.id==t);else {const a=t.replace(/^\//,"");i=n[a],o=e.named_endpoints[t.trim()],s=r.dependencies.find(u=>u.id==n[a]);}if(typeof i!="number")throw new Error("There is no endpoint matching that name of fn_index matching that number.");return {fn_index:i,endpoint_info:o,dependency:s}}class mn{app_reference;options;deep_link=null;config;api_prefix="";api_info;api_map={};session_hash=Math.random().toString(36).substring(2);jwt=!1;last_status={};cookies=null;stream_status={open:!1};closed=!1;pending_stream_messages={};pending_diff_streams={};event_callbacks={};unclosed_events=new Set;heartbeat_event=null;abort_controller=null;stream_instance=null;current_payload;ws_map={};get_url_config(t=null){if(!this.config)throw new Error(ce$2);t===null&&(t=window.location.href);const n=s=>s.replace(/^\/+|\/+$/g,"");let r=n(new URL(this.config.root).pathname),i=n(new URL(t).pathname),o;return i.startsWith(r)?o=n(i.substring(r.length)):o="",this.get_page_config(o)}get_page_config(t){if(!this.config)throw new Error(ce$2);let n=this.config;return t in n.page||(t=""),{...n,current_page:t,layout:n.page[t].layout,components:n.components.filter(r=>n.page[t].components.includes(r.id)),dependencies:this.config.dependencies.filter(r=>n.page[t].dependencies.includes(r.id))}}fetch(t,n){const r=new Headers(n?.headers||{});if(this&&this.cookies&&r.append("Cookie",this.cookies),this&&this.options.headers)for(const i in this.options.headers)r.append(i,this.options.headers[i]);return fetch(t,{...n,headers:r})}stream(t){const n=new Headers;if(this&&this.cookies&&n.append("Cookie",this.cookies),this&&this.options.headers)for(const r in this.options.headers)n.append(r,this.options.headers[r]);return this&&this.options.hf_token&&n.append("Authorization",`Bearer ${this.options.hf_token}`),this.abort_controller=new AbortController,this.stream_instance=js(t.toString(),{credentials:"include",headers:n,signal:this.abort_controller.signal}),this.stream_instance}view_api;upload_files;upload;handle_blob;post_data;submit;predict;open_stream;resolve_config;resolve_cookies;constructor(t,n={events:["data"]}){this.app_reference=t,this.deep_link=n.query_params?.deep_link||null,n.events||(n.events=["data"]),this.options=n,this.current_payload={},this.view_api=ms.bind(this),this.upload_files=As.bind(this),this.handle_blob=ys.bind(this),this.post_data=Es.bind(this),this.submit=Gs.bind(this),this.predict=xs.bind(this),this.open_stream=Rs.bind(this),this.resolve_config=as.bind(this),this.resolve_cookies=cs.bind(this),this.upload=_s.bind(this),this.fetch=this.fetch.bind(this),this.handle_space_success=this.handle_space_success.bind(this),this.stream=this.stream.bind(this);}async init(){if((typeof window>"u"||!("WebSocket"in window))&&!global.WebSocket){const t=await import('./wrapper-CJEAFeIS.js');global.WebSocket=t.WebSocket;}this.options.auth&&await this.resolve_cookies(),await this._resolve_config().then(({config:t})=>this._resolve_heartbeat(t)),this.api_info=await this.view_api(),this.api_map=ss(this.config?.dependencies||[]);}async _resolve_heartbeat(t){if(t&&(this.config=t,this.api_prefix=t.api_prefix||"",this.config&&this.config.connect_heartbeat&&this.config.space_id&&this.options.hf_token&&(this.jwt=await un$2(this.config.space_id,this.options.hf_token,this.cookies))),t.space_id&&this.options.hf_token&&(this.jwt=await un$2(t.space_id,this.options.hf_token)),this.config&&this.config.connect_heartbeat){const n=new URL(`${this.config.root}${this.api_prefix}/${Vo}/${this.session_hash}`);this.jwt&&n.searchParams.set("__sign",this.jwt),this.heartbeat_event||(this.heartbeat_event=this.stream(n));}}static async connect(t,n={events:["data"]}){const r=new this(t,n);return n.session_hash&&(r.session_hash=n.session_hash),await r.init(),r}async reconnect(){const t=new URL(`${this.config.root}${this.api_prefix}/${Ko}`);let n;try{const r=await this.fetch(t);if(!r.ok)throw new Error;n=(await r.json()).app_id;}catch{return "broken"}return n!==this.config.app_id?"changed":"connected"}close(){this.closed=!0,Ht(this.stream_status,this.abort_controller);}set_current_payload(t){this.current_payload=t;}static async duplicate(t,n={events:["data"]}){return Ts(t,n)}async _resolve_config(){const{http_protocol:t,host:n,space_id:r}=await Xe$1(this.app_reference,this.options.hf_token),{status_callback:i}=this.options;r&&i&&await vr$1(r,i);let o;try{let s=`${t}//${n}`;if(o=await this.resolve_config(s),!o)throw new Error(ce$2);return this.config_success(o)}catch(s){if(r&&i)Me$1(r,Ot$1.test(r)?"space_name":"subdomain",this.handle_space_success);else throw i&&i({status:"error",message:"Could not load this space.",load_status:"error",detail:"NOT_FOUND"}),Error(s)}}async config_success(t){if(this.config=t,this.api_prefix=t.api_prefix||"",this.config.auth_required)return this.prepare_return_obj();try{this.api_info=await this.view_api();}catch(n){console.error(Jo+n.message);}return this.prepare_return_obj()}async handle_space_success(t){if(!this)throw new Error(ce$2);const{status_callback:n}=this.options;if(n&&n(t),t.status==="running")try{if(this.config=await this._resolve_config(),this.api_prefix=this?.config?.api_prefix||"",!this.config)throw new Error(ce$2);return await this.config_success(this.config)}catch(r){throw n&&n({status:"error",message:"Could not load this space.",load_status:"error",detail:"NOT_FOUND"}),r}}async component_server(t,n,r){if(!this.config)throw new Error(ce$2);const i={},{hf_token:o}=this.options,{session_hash:s}=this;o&&(i.Authorization=`Bearer ${this.options.hf_token}`);let a,u=this.config.components.find(l=>l.id===t);u?.props?.root_url?a=u.props.root_url:a=this.config.root;let c;if("binary"in r){c=new FormData;for(const l in r.data)l!=="binary"&&c.append(l,r.data[l]);c.set("component_id",t.toString()),c.set("fn_name",n),c.set("session_hash",s);}else c=JSON.stringify({data:r,component_id:t,fn_name:n,session_hash:s}),i["Content-Type"]="application/json";o&&(i.Authorization=`Bearer ${o}`);try{const l=await this.fetch(`${a}${this.api_prefix}/${qo}/`,{method:"POST",body:c,headers:i,credentials:"include"});if(!l.ok)throw new Error("Could not connect to component server: "+l.statusText);return await l.json()}catch(l){console.warn(l);}}set_cookies(t){this.cookies=_r$1(t).join("; ");}prepare_return_obj(){return {config:this.config,predict:this.predict,submit:this.submit,view_api:this.view_api,component_server:this.component_server}}async connect_ws(t){return new Promise((n,r)=>{let i;try{i=new WebSocket(t);}catch{this.ws_map[t]="failed";return}this.ws_map[t]="pending",i.onopen=()=>{this.ws_map[t]=i,n();},i.onerror=o=>{console.error("WebSocket error:",o),this.close_ws(t),this.ws_map[t]="failed",n();},i.onclose=()=>{this.ws_map[t]="closed";},i.onmessage=o=>{};})}async send_ws_message(t,n){if(!(t in this.ws_map))await this.connect_ws(t);else if(this.ws_map[t]==="pending"||this.ws_map[t]==="closed"||this.ws_map[t]==="failed")return;const r=this.ws_map[t];r instanceof WebSocket?r.send(JSON.stringify(n)):this.post_data(t,n);}async close_ws(t){if(t in this.ws_map){const n=this.ws_map[t];n instanceof WebSocket&&(n.close(),delete this.ws_map[t]);}}}

/**
 * @param {any} obj
 * @returns {boolean}
 */
function is_date(obj) {
	return Object.prototype.toString.call(obj) === '[object Date]';
}

/**
 * @template T
 * @param {import('./private.js').TickContext<T>} ctx
 * @param {T} last_value
 * @param {T} current_value
 * @param {T} target_value
 * @returns {T}
 */
function tick_spring(ctx, last_value, current_value, target_value) {
	if (typeof current_value === 'number' || is_date(current_value)) {
		// @ts-ignore
		const delta = target_value - current_value;
		// @ts-ignore
		const velocity = (current_value - last_value) / (ctx.dt || 1 / 60); // guard div by 0
		const spring = ctx.opts.stiffness * delta;
		const damper = ctx.opts.damping * velocity;
		const acceleration = (spring - damper) * ctx.inv_mass;
		const d = (velocity + acceleration) * ctx.dt;
		if (Math.abs(d) < ctx.opts.precision && Math.abs(delta) < ctx.opts.precision) {
			return target_value; // settled
		} else {
			ctx.settled = false; // signal loop to keep ticking
			// @ts-ignore
			return is_date(current_value) ? new Date(current_value.getTime() + d) : current_value + d;
		}
	} else if (Array.isArray(current_value)) {
		// @ts-ignore
		return current_value.map((_, i) =>
			tick_spring(ctx, last_value[i], current_value[i], target_value[i])
		);
	} else if (typeof current_value === 'object') {
		const next_value = {};
		for (const k in current_value) {
			// @ts-ignore
			next_value[k] = tick_spring(ctx, last_value[k], current_value[k], target_value[k]);
		}
		// @ts-ignore
		return next_value;
	} else {
		throw new Error(`Cannot spring ${typeof current_value} values`);
	}
}

/**
 * The spring function in Svelte creates a store whose value is animated, with a motion that simulates the behavior of a spring. This means when the value changes, instead of transitioning at a steady rate, it "bounces" like a spring would, depending on the physics parameters provided. This adds a level of realism to the transitions and can enhance the user experience.
 *
 * https://svelte.dev/docs/svelte-motion#spring
 * @template [T=any]
 * @param {T} [value]
 * @param {import('./private.js').SpringOpts} [opts]
 * @returns {import('./public.js').Spring<T>}
 */
function spring(value, opts = {}) {
	const store = writable(value);
	const { stiffness = 0.15, damping = 0.8, precision = 0.01 } = opts;
	/** @type {number} */
	let last_time;
	/** @type {import('../internal/private.js').Task} */
	let task;
	/** @type {object} */
	let current_token;
	/** @type {T} */
	let last_value = value;
	/** @type {T} */
	let target_value = value;
	let inv_mass = 1;
	let inv_mass_recovery_rate = 0;
	let cancel_task = false;
	/**
	 * @param {T} new_value
	 * @param {import('./private.js').SpringUpdateOpts} opts
	 * @returns {Promise<void>}
	 */
	function set(new_value, opts = {}) {
		target_value = new_value;
		const token = (current_token = {});
		if (value == null || opts.hard || (spring.stiffness >= 1 && spring.damping >= 1)) {
			cancel_task = true; // cancel any running animation
			last_time = now();
			last_value = new_value;
			store.set((value = target_value));
			return Promise.resolve();
		} else if (opts.soft) {
			const rate = opts.soft === true ? 0.5 : +opts.soft;
			inv_mass_recovery_rate = 1 / (rate * 60);
			inv_mass = 0; // infinite mass, unaffected by spring forces
		}
		if (!task) {
			last_time = now();
			cancel_task = false;
			task = loop((now) => {
				if (cancel_task) {
					cancel_task = false;
					task = null;
					return false;
				}
				inv_mass = Math.min(inv_mass + inv_mass_recovery_rate, 1);
				const ctx = {
					inv_mass,
					opts: spring,
					settled: true,
					dt: ((now - last_time) * 60) / 1000
				};
				const next_value = tick_spring(ctx, last_value, value, target_value);
				last_time = now;
				last_value = value;
				store.set((value = next_value));
				if (ctx.settled) {
					task = null;
				}
				return !ctx.settled;
			});
		}
		return new Promise((fulfil) => {
			task.promise.then(() => {
				if (token === current_token) fulfil();
			});
		});
	}
	/** @type {import('./public.js').Spring<T>} */
	const spring = {
		set,
		update: (fn, opts) => set(fn(target_value, value), opts),
		subscribe: store.subscribe,
		stiffness,
		damping,
		precision
	};
	return spring;
}

var W$1={exports:{}};(function(G){var X=typeof window<"u"?window:typeof WorkerGlobalScope<"u"&&self instanceof WorkerGlobalScope?self:{};/**
 * Prism: Lightweight, robust, elegant syntax highlighting
 *
 * @license MIT <https://opensource.org/licenses/MIT>
 * @author Lea Verou <https://lea.verou.me>
 * @namespace
 * @public
 */var i=function(g){var h=/(?:^|\s)lang(?:uage)?-([\w-]+)(?=\s|$)/i,y=0,F={},s={manual:g.Prism&&g.Prism.manual,disableWorkerMessageHandler:g.Prism&&g.Prism.disableWorkerMessageHandler,util:{encode:function t(e){return e instanceof b?new b(e.type,t(e.content),e.alias):Array.isArray(e)?e.map(t):e.replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/\u00a0/g," ")},type:function(t){return Object.prototype.toString.call(t).slice(8,-1)},objId:function(t){return t.__id||Object.defineProperty(t,"__id",{value:++y}),t.__id},clone:function t(e,a){a=a||{};var n,r;switch(s.util.type(e)){case"Object":if(r=s.util.objId(e),a[r])return a[r];n={},a[r]=n;for(var l in e)e.hasOwnProperty(l)&&(n[l]=t(e[l],a));return n;case"Array":return r=s.util.objId(e),a[r]?a[r]:(n=[],a[r]=n,e.forEach(function(o,u){n[u]=t(o,a);}),n);default:return e}},getLanguage:function(t){for(;t;){var e=h.exec(t.className);if(e)return e[1].toLowerCase();t=t.parentElement;}return "none"},setLanguage:function(t,e){t.className=t.className.replace(RegExp(h,"gi"),""),t.classList.add("language-"+e);},currentScript:function(){if(typeof document>"u")return null;if("currentScript"in document)return document.currentScript;try{throw new Error}catch(n){var t=(/at [^(\r\n]*\((.*):[^:]+:[^:]+\)$/i.exec(n.stack)||[])[1];if(t){var e=document.getElementsByTagName("script");for(var a in e)if(e[a].src==t)return e[a]}return null}},isActive:function(t,e,a){for(var n="no-"+e;t;){var r=t.classList;if(r.contains(e))return !0;if(r.contains(n))return !1;t=t.parentElement;}return !!a}},languages:{plain:F,plaintext:F,text:F,txt:F,extend:function(t,e){var a=s.util.clone(s.languages[t]);for(var n in e)a[n]=e[n];return a},insertBefore:function(t,e,a,n){n=n||s.languages;var r=n[t],l={};for(var o in r)if(r.hasOwnProperty(o)){if(o==e)for(var u in a)a.hasOwnProperty(u)&&(l[u]=a[u]);a.hasOwnProperty(o)||(l[o]=r[o]);}var d=n[t];return n[t]=l,s.languages.DFS(s.languages,function(m,A){A===d&&m!=t&&(this[m]=l);}),l},DFS:function t(e,a,n,r){r=r||{};var l=s.util.objId;for(var o in e)if(e.hasOwnProperty(o)){a.call(e,o,e[o],n||o);var u=e[o],d=s.util.type(u);d==="Object"&&!r[l(u)]?(r[l(u)]=!0,t(u,a,null,r)):d==="Array"&&!r[l(u)]&&(r[l(u)]=!0,t(u,a,o,r));}}},plugins:{},highlightAll:function(t,e){s.highlightAllUnder(document,t,e);},highlightAllUnder:function(t,e,a){var n={callback:a,container:t,selector:'code[class*="language-"], [class*="language-"] code, code[class*="lang-"], [class*="lang-"] code'};s.hooks.run("before-highlightall",n),n.elements=Array.prototype.slice.apply(n.container.querySelectorAll(n.selector)),s.hooks.run("before-all-elements-highlight",n);for(var r=0,l;l=n.elements[r++];)s.highlightElement(l,e===!0,n.callback);},highlightElement:function(t,e,a){var n=s.util.getLanguage(t),r=s.languages[n];s.util.setLanguage(t,n);var l=t.parentElement;l&&l.nodeName.toLowerCase()==="pre"&&s.util.setLanguage(l,n);var o=t.textContent,u={element:t,language:n,grammar:r,code:o};function d(A){u.highlightedCode=A,s.hooks.run("before-insert",u),u.element.innerHTML=u.highlightedCode,s.hooks.run("after-highlight",u),s.hooks.run("complete",u),a&&a.call(u.element);}if(s.hooks.run("before-sanity-check",u),l=u.element.parentElement,l&&l.nodeName.toLowerCase()==="pre"&&!l.hasAttribute("tabindex")&&l.setAttribute("tabindex","0"),!u.code){s.hooks.run("complete",u),a&&a.call(u.element);return}if(s.hooks.run("before-highlight",u),!u.grammar){d(s.util.encode(u.code));return}if(e&&g.Worker){var m=new Worker(s.filename);m.onmessage=function(A){d(A.data);},m.postMessage(JSON.stringify({language:u.language,code:u.code,immediateClose:!0}));}else d(s.highlight(u.code,u.grammar,u.language));},highlight:function(t,e,a){var n={code:t,grammar:e,language:a};if(s.hooks.run("before-tokenize",n),!n.grammar)throw new Error('The language "'+n.language+'" has no grammar.');return n.tokens=s.tokenize(n.code,n.grammar),s.hooks.run("after-tokenize",n),b.stringify(s.util.encode(n.tokens),n.language)},tokenize:function(t,e){var a=e.rest;if(a){for(var n in a)e[n]=a[n];delete e.rest;}var r=new _;return S(r,r.head,t),C(t,r,e,r.head,0),P(r)},hooks:{all:{},add:function(t,e){var a=s.hooks.all;a[t]=a[t]||[],a[t].push(e);},run:function(t,e){var a=s.hooks.all[t];if(!(!a||!a.length))for(var n=0,r;r=a[n++];)r(e);}},Token:b};g.Prism=s;function b(t,e,a,n){this.type=t,this.content=e,this.alias=a,this.length=(n||"").length|0;}b.stringify=function t(e,a){if(typeof e=="string")return e;if(Array.isArray(e)){var n="";return e.forEach(function(d){n+=t(d,a);}),n}var r={type:e.type,content:t(e.content,a),tag:"span",classes:["token",e.type],attributes:{},language:a},l=e.alias;l&&(Array.isArray(l)?Array.prototype.push.apply(r.classes,l):r.classes.push(l)),s.hooks.run("wrap",r);var o="";for(var u in r.attributes)o+=" "+u+'="'+(r.attributes[u]||"").replace(/"/g,"&quot;")+'"';return "<"+r.tag+' class="'+r.classes.join(" ")+'"'+o+">"+r.content+"</"+r.tag+">"};function E(t,e,a,n){t.lastIndex=e;var r=t.exec(a);if(r&&n&&r[1]){var l=r[1].length;r.index+=l,r[0]=r[0].slice(l);}return r}function C(t,e,a,n,r,l){for(var o in a)if(!(!a.hasOwnProperty(o)||!a[o])){var u=a[o];u=Array.isArray(u)?u:[u];for(var d=0;d<u.length;++d){if(l&&l.cause==o+","+d)return;var m=u[d],A=m.inside,H=!!m.lookbehind,q=!!m.greedy,Y=m.alias;if(q&&!m.pattern.global){var J=m.pattern.toString().match(/[imsuy]*$/)[0];m.pattern=RegExp(m.pattern.source,J+"g");}for(var Z=m.pattern||m,v=n.next,w=r;v!==e.tail&&!(l&&w>=l.reach);w+=v.value.length,v=v.next){var $=v.value;if(e.length>t.length)return;if(!($ instanceof b)){var z=1,x;if(q){if(x=E(Z,w,t,H),!x||x.index>=t.length)break;var L=x.index,N=x.index+x[0].length,k=w;for(k+=v.value.length;L>=k;)v=v.next,k+=v.value.length;if(k-=v.value.length,w=k,v.value instanceof b)continue;for(var T=v;T!==e.tail&&(k<N||typeof T.value=="string");T=T.next)z++,k+=T.value.length;z--,$=t.slice(w,k),x.index-=w;}else if(x=E(Z,0,$,H),!x)continue;var L=x.index,D=x[0],M=$.slice(0,L),B=$.slice(L+D.length),O=w+$.length;l&&O>l.reach&&(l.reach=O);var I=v.prev;M&&(I=S(e,I,M),w+=M.length),j(e,I,z);var K=new b(o,A?s.tokenize(D,A):D,Y,D);if(v=S(e,I,K),B&&S(e,v,B),z>1){var R={cause:o+","+d,reach:O};C(t,e,a,v.prev,w,R),l&&R.reach>l.reach&&(l.reach=R.reach);}}}}}}function _(){var t={value:null,prev:null,next:null},e={value:null,prev:t,next:null};t.next=e,this.head=t,this.tail=e,this.length=0;}function S(t,e,a){var n=e.next,r={value:a,prev:e,next:n};return e.next=r,n.prev=r,t.length++,r}function j(t,e,a){for(var n=e.next,r=0;r<a&&n!==t.tail;r++)n=n.next;e.next=n,n.prev=e,t.length-=r;}function P(t){for(var e=[],a=t.head.next;a!==t.tail;)e.push(a.value),a=a.next;return e}if(!g.document)return g.addEventListener&&(s.disableWorkerMessageHandler||g.addEventListener("message",function(t){var e=JSON.parse(t.data),a=e.language,n=e.code,r=e.immediateClose;g.postMessage(s.highlight(n,s.languages[a],a)),r&&g.close();},!1)),s;var p=s.util.currentScript();p&&(s.filename=p.src,p.hasAttribute("data-manual")&&(s.manual=!0));function c(){s.manual||s.highlightAll();}if(!s.manual){var f=document.readyState;f==="loading"||f==="interactive"&&p&&p.defer?document.addEventListener("DOMContentLoaded",c):window.requestAnimationFrame?window.requestAnimationFrame(c):window.setTimeout(c,16);}return s}(X);G.exports&&(G.exports=i),typeof qs<"u"&&(qs.Prism=i),i.languages.markup={comment:{pattern:/<!--(?:(?!<!--)[\s\S])*?-->/,greedy:!0},prolog:{pattern:/<\?[\s\S]+?\?>/,greedy:!0},doctype:{pattern:/<!DOCTYPE(?:[^>"'[\]]|"[^"]*"|'[^']*')+(?:\[(?:[^<"'\]]|"[^"]*"|'[^']*'|<(?!!--)|<!--(?:[^-]|-(?!->))*-->)*\]\s*)?>/i,greedy:!0,inside:{"internal-subset":{pattern:/(^[^\[]*\[)[\s\S]+(?=\]>$)/,lookbehind:!0,greedy:!0,inside:null},string:{pattern:/"[^"]*"|'[^']*'/,greedy:!0},punctuation:/^<!|>$|[[\]]/,"doctype-tag":/^DOCTYPE/i,name:/[^\s<>'"]+/}},cdata:{pattern:/<!\[CDATA\[[\s\S]*?\]\]>/i,greedy:!0},tag:{pattern:/<\/?(?!\d)[^\s>\/=$<%]+(?:\s(?:\s*[^\s>\/=]+(?:\s*=\s*(?:"[^"]*"|'[^']*'|[^\s'">=]+(?=[\s>]))|(?=[\s/>])))+)?\s*\/?>/,greedy:!0,inside:{tag:{pattern:/^<\/?[^\s>\/]+/,inside:{punctuation:/^<\/?/,namespace:/^[^\s>\/:]+:/}},"special-attr":[],"attr-value":{pattern:/=\s*(?:"[^"]*"|'[^']*'|[^\s'">=]+)/,inside:{punctuation:[{pattern:/^=/,alias:"attr-equals"},{pattern:/^(\s*)["']|["']$/,lookbehind:!0}]}},punctuation:/\/?>/,"attr-name":{pattern:/[^\s>\/]+/,inside:{namespace:/^[^\s>\/:]+:/}}}},entity:[{pattern:/&[\da-z]{1,8};/i,alias:"named-entity"},/&#x?[\da-f]{1,8};/i]},i.languages.markup.tag.inside["attr-value"].inside.entity=i.languages.markup.entity,i.languages.markup.doctype.inside["internal-subset"].inside=i.languages.markup,i.hooks.add("wrap",function(g){g.type==="entity"&&(g.attributes.title=g.content.replace(/&amp;/,"&"));}),Object.defineProperty(i.languages.markup.tag,"addInlined",{value:function(h,y){var F={};F["language-"+y]={pattern:/(^<!\[CDATA\[)[\s\S]+?(?=\]\]>$)/i,lookbehind:!0,inside:i.languages[y]},F.cdata=/^<!\[CDATA\[|\]\]>$/i;var s={"included-cdata":{pattern:/<!\[CDATA\[[\s\S]*?\]\]>/i,inside:F}};s["language-"+y]={pattern:/[\s\S]+/,inside:i.languages[y]};var b={};b[h]={pattern:RegExp(/(<__[^>]*>)(?:<!\[CDATA\[(?:[^\]]|\](?!\]>))*\]\]>|(?!<!\[CDATA\[)[\s\S])*?(?=<\/__>)/.source.replace(/__/g,function(){return h}),"i"),lookbehind:!0,greedy:!0,inside:s},i.languages.insertBefore("markup","cdata",b);}}),Object.defineProperty(i.languages.markup.tag,"addAttribute",{value:function(g,h){i.languages.markup.tag.inside["special-attr"].push({pattern:RegExp(/(^|["'\s])/.source+"(?:"+g+")"+/\s*=\s*(?:"[^"]*"|'[^']*'|[^\s'">=]+(?=[\s>]))/.source,"i"),lookbehind:!0,inside:{"attr-name":/^[^\s=]+/,"attr-value":{pattern:/=[\s\S]+/,inside:{value:{pattern:/(^=\s*(["']|(?!["'])))\S[\s\S]*(?=\2$)/,lookbehind:!0,alias:[h,"language-"+h],inside:i.languages[h]},punctuation:[{pattern:/^=/,alias:"attr-equals"},/"|'/]}}}});}}),i.languages.html=i.languages.markup,i.languages.mathml=i.languages.markup,i.languages.svg=i.languages.markup,i.languages.xml=i.languages.extend("markup",{}),i.languages.ssml=i.languages.xml,i.languages.atom=i.languages.xml,i.languages.rss=i.languages.xml,function(g){var h=/(?:"(?:\\(?:\r\n|[\s\S])|[^"\\\r\n])*"|'(?:\\(?:\r\n|[\s\S])|[^'\\\r\n])*')/;g.languages.css={comment:/\/\*[\s\S]*?\*\//,atrule:{pattern:RegExp("@[\\w-](?:"+/[^;{\s"']|\s+(?!\s)/.source+"|"+h.source+")*?"+/(?:;|(?=\s*\{))/.source),inside:{rule:/^@[\w-]+/,"selector-function-argument":{pattern:/(\bselector\s*\(\s*(?![\s)]))(?:[^()\s]|\s+(?![\s)])|\((?:[^()]|\([^()]*\))*\))+(?=\s*\))/,lookbehind:!0,alias:"selector"},keyword:{pattern:/(^|[^\w-])(?:and|not|only|or)(?![\w-])/,lookbehind:!0}}},url:{pattern:RegExp("\\burl\\((?:"+h.source+"|"+/(?:[^\\\r\n()"']|\\[\s\S])*/.source+")\\)","i"),greedy:!0,inside:{function:/^url/i,punctuation:/^\(|\)$/,string:{pattern:RegExp("^"+h.source+"$"),alias:"url"}}},selector:{pattern:RegExp(`(^|[{}\\s])[^{}\\s](?:[^{};"'\\s]|\\s+(?![\\s{])|`+h.source+")*(?=\\s*\\{)"),lookbehind:!0},string:{pattern:h,greedy:!0},property:{pattern:/(^|[^-\w\xA0-\uFFFF])(?!\s)[-_a-z\xA0-\uFFFF](?:(?!\s)[-\w\xA0-\uFFFF])*(?=\s*:)/i,lookbehind:!0},important:/!important\b/i,function:{pattern:/(^|[^-a-z0-9])[-a-z0-9]+(?=\()/i,lookbehind:!0},punctuation:/[(){};:,]/},g.languages.css.atrule.inside.rest=g.languages.css;var y=g.languages.markup;y&&(y.tag.addInlined("style","css"),y.tag.addAttribute("style","css"));}(i),i.languages.clike={comment:[{pattern:/(^|[^\\])\/\*[\s\S]*?(?:\*\/|$)/,lookbehind:!0,greedy:!0},{pattern:/(^|[^\\:])\/\/.*/,lookbehind:!0,greedy:!0}],string:{pattern:/(["'])(?:\\(?:\r\n|[\s\S])|(?!\1)[^\\\r\n])*\1/,greedy:!0},"class-name":{pattern:/(\b(?:class|extends|implements|instanceof|interface|new|trait)\s+|\bcatch\s+\()[\w.\\]+/i,lookbehind:!0,inside:{punctuation:/[.\\]/}},keyword:/\b(?:break|catch|continue|do|else|finally|for|function|if|in|instanceof|new|null|return|throw|try|while)\b/,boolean:/\b(?:false|true)\b/,function:/\b\w+(?=\()/,number:/\b0x[\da-f]+\b|(?:\b\d+(?:\.\d*)?|\B\.\d+)(?:e[+-]?\d+)?/i,operator:/[<>]=?|[!=]=?=?|--?|\+\+?|&&?|\|\|?|[?*/~^%]/,punctuation:/[{}[\];(),.:]/},i.languages.javascript=i.languages.extend("clike",{"class-name":[i.languages.clike["class-name"],{pattern:/(^|[^$\w\xA0-\uFFFF])(?!\s)[_$A-Z\xA0-\uFFFF](?:(?!\s)[$\w\xA0-\uFFFF])*(?=\.(?:constructor|prototype))/,lookbehind:!0}],keyword:[{pattern:/((?:^|\})\s*)catch\b/,lookbehind:!0},{pattern:/(^|[^.]|\.\.\.\s*)\b(?:as|assert(?=\s*\{)|async(?=\s*(?:function\b|\(|[$\w\xA0-\uFFFF]|$))|await|break|case|class|const|continue|debugger|default|delete|do|else|enum|export|extends|finally(?=\s*(?:\{|$))|for|from(?=\s*(?:['"]|$))|function|(?:get|set)(?=\s*(?:[#\[$\w\xA0-\uFFFF]|$))|if|implements|import|in|instanceof|interface|let|new|null|of|package|private|protected|public|return|static|super|switch|this|throw|try|typeof|undefined|var|void|while|with|yield)\b/,lookbehind:!0}],function:/#?(?!\s)[_$a-zA-Z\xA0-\uFFFF](?:(?!\s)[$\w\xA0-\uFFFF])*(?=\s*(?:\.\s*(?:apply|bind|call)\s*)?\()/,number:{pattern:RegExp(/(^|[^\w$])/.source+"(?:"+(/NaN|Infinity/.source+"|"+/0[bB][01]+(?:_[01]+)*n?/.source+"|"+/0[oO][0-7]+(?:_[0-7]+)*n?/.source+"|"+/0[xX][\dA-Fa-f]+(?:_[\dA-Fa-f]+)*n?/.source+"|"+/\d+(?:_\d+)*n/.source+"|"+/(?:\d+(?:_\d+)*(?:\.(?:\d+(?:_\d+)*)?)?|\.\d+(?:_\d+)*)(?:[Ee][+-]?\d+(?:_\d+)*)?/.source)+")"+/(?![\w$])/.source),lookbehind:!0},operator:/--|\+\+|\*\*=?|=>|&&=?|\|\|=?|[!=]==|<<=?|>>>?=?|[-+*/%&|^!=<>]=?|\.{3}|\?\?=?|\?\.?|[~:]/}),i.languages.javascript["class-name"][0].pattern=/(\b(?:class|extends|implements|instanceof|interface|new)\s+)[\w.\\]+/,i.languages.insertBefore("javascript","keyword",{regex:{pattern:RegExp(/((?:^|[^$\w\xA0-\uFFFF."'\])\s]|\b(?:return|yield))\s*)/.source+/\//.source+"(?:"+/(?:\[(?:[^\]\\\r\n]|\\.)*\]|\\.|[^/\\\[\r\n])+\/[dgimyus]{0,7}/.source+"|"+/(?:\[(?:[^[\]\\\r\n]|\\.|\[(?:[^[\]\\\r\n]|\\.|\[(?:[^[\]\\\r\n]|\\.)*\])*\])*\]|\\.|[^/\\\[\r\n])+\/[dgimyus]{0,7}v[dgimyus]{0,7}/.source+")"+/(?=(?:\s|\/\*(?:[^*]|\*(?!\/))*\*\/)*(?:$|[\r\n,.;:})\]]|\/\/))/.source),lookbehind:!0,greedy:!0,inside:{"regex-source":{pattern:/^(\/)[\s\S]+(?=\/[a-z]*$)/,lookbehind:!0,alias:"language-regex",inside:i.languages.regex},"regex-delimiter":/^\/|\/$/,"regex-flags":/^[a-z]+$/}},"function-variable":{pattern:/#?(?!\s)[_$a-zA-Z\xA0-\uFFFF](?:(?!\s)[$\w\xA0-\uFFFF])*(?=\s*[=:]\s*(?:async\s*)?(?:\bfunction\b|(?:\((?:[^()]|\([^()]*\))*\)|(?!\s)[_$a-zA-Z\xA0-\uFFFF](?:(?!\s)[$\w\xA0-\uFFFF])*)\s*=>))/,alias:"function"},parameter:[{pattern:/(function(?:\s+(?!\s)[_$a-zA-Z\xA0-\uFFFF](?:(?!\s)[$\w\xA0-\uFFFF])*)?\s*\(\s*)(?!\s)(?:[^()\s]|\s+(?![\s)])|\([^()]*\))+(?=\s*\))/,lookbehind:!0,inside:i.languages.javascript},{pattern:/(^|[^$\w\xA0-\uFFFF])(?!\s)[_$a-z\xA0-\uFFFF](?:(?!\s)[$\w\xA0-\uFFFF])*(?=\s*=>)/i,lookbehind:!0,inside:i.languages.javascript},{pattern:/(\(\s*)(?!\s)(?:[^()\s]|\s+(?![\s)])|\([^()]*\))+(?=\s*\)\s*=>)/,lookbehind:!0,inside:i.languages.javascript},{pattern:/((?:\b|\s|^)(?!(?:as|async|await|break|case|catch|class|const|continue|debugger|default|delete|do|else|enum|export|extends|finally|for|from|function|get|if|implements|import|in|instanceof|interface|let|new|null|of|package|private|protected|public|return|set|static|super|switch|this|throw|try|typeof|undefined|var|void|while|with|yield)(?![$\w\xA0-\uFFFF]))(?:(?!\s)[_$a-zA-Z\xA0-\uFFFF](?:(?!\s)[$\w\xA0-\uFFFF])*\s*)\(\s*|\]\s*\(\s*)(?!\s)(?:[^()\s]|\s+(?![\s)])|\([^()]*\))+(?=\s*\)\s*\{)/,lookbehind:!0,inside:i.languages.javascript}],constant:/\b[A-Z](?:[A-Z_]|\dx?)*\b/}),i.languages.insertBefore("javascript","string",{hashbang:{pattern:/^#!.*/,greedy:!0,alias:"comment"},"template-string":{pattern:/`(?:\\[\s\S]|\$\{(?:[^{}]|\{(?:[^{}]|\{[^}]*\})*\})+\}|(?!\$\{)[^\\`])*`/,greedy:!0,inside:{"template-punctuation":{pattern:/^`|`$/,alias:"string"},interpolation:{pattern:/((?:^|[^\\])(?:\\{2})*)\$\{(?:[^{}]|\{(?:[^{}]|\{[^}]*\})*\})+\}/,lookbehind:!0,inside:{"interpolation-punctuation":{pattern:/^\$\{|\}$/,alias:"punctuation"},rest:i.languages.javascript}},string:/[\s\S]+/}},"string-property":{pattern:/((?:^|[,{])[ \t]*)(["'])(?:\\(?:\r\n|[\s\S])|(?!\2)[^\\\r\n])*\2(?=\s*:)/m,lookbehind:!0,greedy:!0,alias:"property"}}),i.languages.insertBefore("javascript","operator",{"literal-property":{pattern:/((?:^|[,{])[ \t]*)(?!\s)[_$a-zA-Z\xA0-\uFFFF](?:(?!\s)[$\w\xA0-\uFFFF])*(?=\s*:)/m,lookbehind:!0,alias:"property"}}),i.languages.markup&&(i.languages.markup.tag.addInlined("script","javascript"),i.languages.markup.tag.addAttribute(/on(?:abort|blur|change|click|composition(?:end|start|update)|dblclick|error|focus(?:in|out)?|key(?:down|up)|load|mouse(?:down|enter|leave|move|out|over|up)|reset|resize|scroll|select|slotchange|submit|unload|wheel)/.source,"javascript")),i.languages.js=i.languages.javascript,function(){if(typeof i>"u"||typeof document>"u")return;Element.prototype.matches||(Element.prototype.matches=Element.prototype.msMatchesSelector||Element.prototype.webkitMatchesSelector);var g="Loading…",h=function(p,c){return "✖ Error "+p+" while fetching file: "+c},y="✖ Error: File does not exist or is empty",F={js:"javascript",py:"python",rb:"ruby",ps1:"powershell",psm1:"powershell",sh:"bash",bat:"batch",h:"c",tex:"latex"},s="data-src-status",b="loading",E="loaded",C="failed",_="pre[data-src]:not(["+s+'="'+E+'"]):not(['+s+'="'+b+'"])';function S(p,c,f){var t=new XMLHttpRequest;t.open("GET",p,!0),t.onreadystatechange=function(){t.readyState==4&&(t.status<400&&t.responseText?c(t.responseText):t.status>=400?f(h(t.status,t.statusText)):f(y));},t.send(null);}function j(p){var c=/^\s*(\d+)\s*(?:(,)\s*(?:(\d+)\s*)?)?$/.exec(p||"");if(c){var f=Number(c[1]),t=c[2],e=c[3];return t?e?[f,Number(e)]:[f,void 0]:[f,f]}}i.hooks.add("before-highlightall",function(p){p.selector+=", "+_;}),i.hooks.add("before-sanity-check",function(p){var c=p.element;if(c.matches(_)){p.code="",c.setAttribute(s,b);var f=c.appendChild(document.createElement("CODE"));f.textContent=g;var t=c.getAttribute("data-src"),e=p.language;if(e==="none"){var a=(/\.(\w+)$/.exec(t)||[,"none"])[1];e=F[a]||a;}i.util.setLanguage(f,e),i.util.setLanguage(c,e);var n=i.plugins.autoloader;n&&n.loadLanguages(e),S(t,function(r){c.setAttribute(s,E);var l=j(c.getAttribute("data-range"));if(l){var o=r.split(/\r\n?|\n/g),u=l[0],d=l[1]==null?o.length:l[1];u<0&&(u+=o.length),u=Math.max(0,Math.min(u-1,o.length)),d<0&&(d+=o.length),d=Math.max(0,Math.min(d,o.length)),r=o.slice(u,d).join(`
`),c.hasAttribute("data-start")||c.setAttribute("data-start",String(u+1));}f.textContent=r,i.highlightElement(f);},function(r){c.setAttribute(s,C),f.textContent=r;});}}),i.plugins.fileHighlight={highlight:function(c){for(var f=(c||document).querySelectorAll(_),t=0,e;e=f[t++];)i.highlightElement(e);}};var P=!1;i.fileHighlight=function(){P||(console.warn("Prism.fileHighlight is deprecated. Use `Prism.plugins.fileHighlight.highlight` instead."),P=!0),i.plugins.fileHighlight.highlight.apply(this,arguments);};}();})(W$1);var V$1=W$1.exports;const te$2=Ir$1(V$1);Prism.languages.python={comment:{pattern:/(^|[^\\])#.*/,lookbehind:!0,greedy:!0},"string-interpolation":{pattern:/(?:f|fr|rf)(?:("""|''')[\s\S]*?\1|("|')(?:\\.|(?!\2)[^\\\r\n])*\2)/i,greedy:!0,inside:{interpolation:{pattern:/((?:^|[^{])(?:\{\{)*)\{(?!\{)(?:[^{}]|\{(?!\{)(?:[^{}]|\{(?!\{)(?:[^{}])+\})+\})+\}/,lookbehind:!0,inside:{"format-spec":{pattern:/(:)[^:(){}]+(?=\}$)/,lookbehind:!0},"conversion-option":{pattern:/![sra](?=[:}]$)/,alias:"punctuation"},rest:null}},string:/[\s\S]+/}},"triple-quoted-string":{pattern:/(?:[rub]|br|rb)?("""|''')[\s\S]*?\1/i,greedy:!0,alias:"string"},string:{pattern:/(?:[rub]|br|rb)?("|')(?:\\.|(?!\1)[^\\\r\n])*\1/i,greedy:!0},function:{pattern:/((?:^|\s)def[ \t]+)[a-zA-Z_]\w*(?=\s*\()/g,lookbehind:!0},"class-name":{pattern:/(\bclass\s+)\w+/i,lookbehind:!0},decorator:{pattern:/(^[\t ]*)@\w+(?:\.\w+)*/m,lookbehind:!0,alias:["annotation","punctuation"],inside:{punctuation:/\./}},keyword:/\b(?:_(?=\s*:)|and|as|assert|async|await|break|case|class|continue|def|del|elif|else|except|exec|finally|for|from|global|if|import|in|is|lambda|match|nonlocal|not|or|pass|print|raise|return|try|while|with|yield)\b/,builtin:/\b(?:__import__|abs|all|any|apply|ascii|basestring|bin|bool|buffer|bytearray|bytes|callable|chr|classmethod|cmp|coerce|compile|complex|delattr|dict|dir|divmod|enumerate|eval|execfile|file|filter|float|format|frozenset|getattr|globals|hasattr|hash|help|hex|id|input|int|intern|isinstance|issubclass|iter|len|list|locals|long|map|max|memoryview|min|next|object|oct|open|ord|pow|property|range|raw_input|reduce|reload|repr|reversed|round|set|setattr|slice|sorted|staticmethod|str|sum|super|tuple|type|unichr|unicode|vars|xrange|zip)\b/,boolean:/\b(?:False|None|True)\b/,number:/\b0(?:b(?:_?[01])+|o(?:_?[0-7])+|x(?:_?[a-f0-9])+)\b|(?:\b\d+(?:_\d+)*(?:\.(?:\d+(?:_\d+)*)?)?|\B\.\d+(?:_\d+)*)(?:e[+-]?\d+(?:_\d+)*)?j?(?!\w)/i,operator:/[-+%=]=?|!=|:=|\*\*?=?|\/\/?=?|<[<=>]?|>[=>]?|[&|^~]/,punctuation:/[{}[\];(),.:]/};Prism.languages.python["string-interpolation"].inside.interpolation.inside.rest=Prism.languages.python;Prism.languages.py=Prism.languages.python;

function getDefaultExportFromCjs (x) {
	return x && x.__esModule && Object.prototype.hasOwnProperty.call(x, 'default') ? x['default'] : x;
}

var picocolors = {exports: {}};

var hasRequiredPicocolors;

function requirePicocolors () {
	if (hasRequiredPicocolors) return picocolors.exports;
	hasRequiredPicocolors = 1;
	let p = process || {}, argv = p.argv || [], env = p.env || {};
	let isColorSupported =
		!(!!env.NO_COLOR || argv.includes("--no-color")) &&
		(!!env.FORCE_COLOR || argv.includes("--color") || p.platform === "win32" || ((p.stdout || {}).isTTY && env.TERM !== "dumb") || !!env.CI);

	let formatter = (open, close, replace = open) =>
		input => {
			let string = "" + input, index = string.indexOf(close, open.length);
			return ~index ? open + replaceClose(string, close, replace, index) + close : open + string + close
		};

	let replaceClose = (string, close, replace, index) => {
		let result = "", cursor = 0;
		do {
			result += string.substring(cursor, index) + replace;
			cursor = index + close.length;
			index = string.indexOf(close, cursor);
		} while (~index)
		return result + string.substring(cursor)
	};

	let createColors = (enabled = isColorSupported) => {
		let f = enabled ? formatter : () => String;
		return {
			isColorSupported: enabled,
			reset: f("\x1b[0m", "\x1b[0m"),
			bold: f("\x1b[1m", "\x1b[22m", "\x1b[22m\x1b[1m"),
			dim: f("\x1b[2m", "\x1b[22m", "\x1b[22m\x1b[2m"),
			italic: f("\x1b[3m", "\x1b[23m"),
			underline: f("\x1b[4m", "\x1b[24m"),
			inverse: f("\x1b[7m", "\x1b[27m"),
			hidden: f("\x1b[8m", "\x1b[28m"),
			strikethrough: f("\x1b[9m", "\x1b[29m"),

			black: f("\x1b[30m", "\x1b[39m"),
			red: f("\x1b[31m", "\x1b[39m"),
			green: f("\x1b[32m", "\x1b[39m"),
			yellow: f("\x1b[33m", "\x1b[39m"),
			blue: f("\x1b[34m", "\x1b[39m"),
			magenta: f("\x1b[35m", "\x1b[39m"),
			cyan: f("\x1b[36m", "\x1b[39m"),
			white: f("\x1b[37m", "\x1b[39m"),
			gray: f("\x1b[90m", "\x1b[39m"),

			bgBlack: f("\x1b[40m", "\x1b[49m"),
			bgRed: f("\x1b[41m", "\x1b[49m"),
			bgGreen: f("\x1b[42m", "\x1b[49m"),
			bgYellow: f("\x1b[43m", "\x1b[49m"),
			bgBlue: f("\x1b[44m", "\x1b[49m"),
			bgMagenta: f("\x1b[45m", "\x1b[49m"),
			bgCyan: f("\x1b[46m", "\x1b[49m"),
			bgWhite: f("\x1b[47m", "\x1b[49m"),

			blackBright: f("\x1b[90m", "\x1b[39m"),
			redBright: f("\x1b[91m", "\x1b[39m"),
			greenBright: f("\x1b[92m", "\x1b[39m"),
			yellowBright: f("\x1b[93m", "\x1b[39m"),
			blueBright: f("\x1b[94m", "\x1b[39m"),
			magentaBright: f("\x1b[95m", "\x1b[39m"),
			cyanBright: f("\x1b[96m", "\x1b[39m"),
			whiteBright: f("\x1b[97m", "\x1b[39m"),

			bgBlackBright: f("\x1b[100m", "\x1b[49m"),
			bgRedBright: f("\x1b[101m", "\x1b[49m"),
			bgGreenBright: f("\x1b[102m", "\x1b[49m"),
			bgYellowBright: f("\x1b[103m", "\x1b[49m"),
			bgBlueBright: f("\x1b[104m", "\x1b[49m"),
			bgMagentaBright: f("\x1b[105m", "\x1b[49m"),
			bgCyanBright: f("\x1b[106m", "\x1b[49m"),
			bgWhiteBright: f("\x1b[107m", "\x1b[49m"),
		}
	};

	picocolors.exports = createColors();
	picocolors.exports.createColors = createColors;
	return picocolors.exports;
}

var tokenize;
var hasRequiredTokenize;

function requireTokenize () {
	if (hasRequiredTokenize) return tokenize;
	hasRequiredTokenize = 1;

	const SINGLE_QUOTE = "'".charCodeAt(0);
	const DOUBLE_QUOTE = '"'.charCodeAt(0);
	const BACKSLASH = '\\'.charCodeAt(0);
	const SLASH = '/'.charCodeAt(0);
	const NEWLINE = '\n'.charCodeAt(0);
	const SPACE = ' '.charCodeAt(0);
	const FEED = '\f'.charCodeAt(0);
	const TAB = '\t'.charCodeAt(0);
	const CR = '\r'.charCodeAt(0);
	const OPEN_SQUARE = '['.charCodeAt(0);
	const CLOSE_SQUARE = ']'.charCodeAt(0);
	const OPEN_PARENTHESES = '('.charCodeAt(0);
	const CLOSE_PARENTHESES = ')'.charCodeAt(0);
	const OPEN_CURLY = '{'.charCodeAt(0);
	const CLOSE_CURLY = '}'.charCodeAt(0);
	const SEMICOLON = ';'.charCodeAt(0);
	const ASTERISK = '*'.charCodeAt(0);
	const COLON = ':'.charCodeAt(0);
	const AT = '@'.charCodeAt(0);

	const RE_AT_END = /[\t\n\f\r "#'()/;[\\\]{}]/g;
	const RE_WORD_END = /[\t\n\f\r !"#'():;@[\\\]{}]|\/(?=\*)/g;
	const RE_BAD_BRACKET = /.[\r\n"'(/\\]/;
	const RE_HEX_ESCAPE = /[\da-f]/i;

	tokenize = function tokenizer(input, options = {}) {
	  let css = input.css.valueOf();
	  let ignore = options.ignoreErrors;

	  let code, next, quote, content, escape;
	  let escaped, escapePos, prev, n, currentToken;

	  let length = css.length;
	  let pos = 0;
	  let buffer = [];
	  let returned = [];

	  function position() {
	    return pos
	  }

	  function unclosed(what) {
	    throw input.error('Unclosed ' + what, pos)
	  }

	  function endOfFile() {
	    return returned.length === 0 && pos >= length
	  }

	  function nextToken(opts) {
	    if (returned.length) return returned.pop()
	    if (pos >= length) return

	    let ignoreUnclosed = opts ? opts.ignoreUnclosed : false;

	    code = css.charCodeAt(pos);

	    switch (code) {
	      case NEWLINE:
	      case SPACE:
	      case TAB:
	      case CR:
	      case FEED: {
	        next = pos;
	        do {
	          next += 1;
	          code = css.charCodeAt(next);
	        } while (
	          code === SPACE ||
	          code === NEWLINE ||
	          code === TAB ||
	          code === CR ||
	          code === FEED
	        )

	        currentToken = ['space', css.slice(pos, next)];
	        pos = next - 1;
	        break
	      }

	      case OPEN_SQUARE:
	      case CLOSE_SQUARE:
	      case OPEN_CURLY:
	      case CLOSE_CURLY:
	      case COLON:
	      case SEMICOLON:
	      case CLOSE_PARENTHESES: {
	        let controlChar = String.fromCharCode(code);
	        currentToken = [controlChar, controlChar, pos];
	        break
	      }

	      case OPEN_PARENTHESES: {
	        prev = buffer.length ? buffer.pop()[1] : '';
	        n = css.charCodeAt(pos + 1);
	        if (
	          prev === 'url' &&
	          n !== SINGLE_QUOTE &&
	          n !== DOUBLE_QUOTE &&
	          n !== SPACE &&
	          n !== NEWLINE &&
	          n !== TAB &&
	          n !== FEED &&
	          n !== CR
	        ) {
	          next = pos;
	          do {
	            escaped = false;
	            next = css.indexOf(')', next + 1);
	            if (next === -1) {
	              if (ignore || ignoreUnclosed) {
	                next = pos;
	                break
	              } else {
	                unclosed('bracket');
	              }
	            }
	            escapePos = next;
	            while (css.charCodeAt(escapePos - 1) === BACKSLASH) {
	              escapePos -= 1;
	              escaped = !escaped;
	            }
	          } while (escaped)

	          currentToken = ['brackets', css.slice(pos, next + 1), pos, next];

	          pos = next;
	        } else {
	          next = css.indexOf(')', pos + 1);
	          content = css.slice(pos, next + 1);

	          if (next === -1 || RE_BAD_BRACKET.test(content)) {
	            currentToken = ['(', '(', pos];
	          } else {
	            currentToken = ['brackets', content, pos, next];
	            pos = next;
	          }
	        }

	        break
	      }

	      case SINGLE_QUOTE:
	      case DOUBLE_QUOTE: {
	        quote = code === SINGLE_QUOTE ? "'" : '"';
	        next = pos;
	        do {
	          escaped = false;
	          next = css.indexOf(quote, next + 1);
	          if (next === -1) {
	            if (ignore || ignoreUnclosed) {
	              next = pos + 1;
	              break
	            } else {
	              unclosed('string');
	            }
	          }
	          escapePos = next;
	          while (css.charCodeAt(escapePos - 1) === BACKSLASH) {
	            escapePos -= 1;
	            escaped = !escaped;
	          }
	        } while (escaped)

	        currentToken = ['string', css.slice(pos, next + 1), pos, next];
	        pos = next;
	        break
	      }

	      case AT: {
	        RE_AT_END.lastIndex = pos + 1;
	        RE_AT_END.test(css);
	        if (RE_AT_END.lastIndex === 0) {
	          next = css.length - 1;
	        } else {
	          next = RE_AT_END.lastIndex - 2;
	        }

	        currentToken = ['at-word', css.slice(pos, next + 1), pos, next];

	        pos = next;
	        break
	      }

	      case BACKSLASH: {
	        next = pos;
	        escape = true;
	        while (css.charCodeAt(next + 1) === BACKSLASH) {
	          next += 1;
	          escape = !escape;
	        }
	        code = css.charCodeAt(next + 1);
	        if (
	          escape &&
	          code !== SLASH &&
	          code !== SPACE &&
	          code !== NEWLINE &&
	          code !== TAB &&
	          code !== CR &&
	          code !== FEED
	        ) {
	          next += 1;
	          if (RE_HEX_ESCAPE.test(css.charAt(next))) {
	            while (RE_HEX_ESCAPE.test(css.charAt(next + 1))) {
	              next += 1;
	            }
	            if (css.charCodeAt(next + 1) === SPACE) {
	              next += 1;
	            }
	          }
	        }

	        currentToken = ['word', css.slice(pos, next + 1), pos, next];

	        pos = next;
	        break
	      }

	      default: {
	        if (code === SLASH && css.charCodeAt(pos + 1) === ASTERISK) {
	          next = css.indexOf('*/', pos + 2) + 1;
	          if (next === 0) {
	            if (ignore || ignoreUnclosed) {
	              next = css.length;
	            } else {
	              unclosed('comment');
	            }
	          }

	          currentToken = ['comment', css.slice(pos, next + 1), pos, next];
	          pos = next;
	        } else {
	          RE_WORD_END.lastIndex = pos + 1;
	          RE_WORD_END.test(css);
	          if (RE_WORD_END.lastIndex === 0) {
	            next = css.length - 1;
	          } else {
	            next = RE_WORD_END.lastIndex - 2;
	          }

	          currentToken = ['word', css.slice(pos, next + 1), pos, next];
	          buffer.push(currentToken);
	          pos = next;
	        }

	        break
	      }
	    }

	    pos++;
	    return currentToken
	  }

	  function back(token) {
	    returned.push(token);
	  }

	  return {
	    back,
	    endOfFile,
	    nextToken,
	    position
	  }
	};
	return tokenize;
}

var terminalHighlight_1;
var hasRequiredTerminalHighlight;

function requireTerminalHighlight () {
	if (hasRequiredTerminalHighlight) return terminalHighlight_1;
	hasRequiredTerminalHighlight = 1;

	let pico = requirePicocolors();

	let tokenizer = requireTokenize();

	let Input;

	function registerInput(dependant) {
	  Input = dependant;
	}

	const HIGHLIGHT_THEME = {
	  ';': pico.yellow,
	  ':': pico.yellow,
	  '(': pico.cyan,
	  ')': pico.cyan,
	  '[': pico.yellow,
	  ']': pico.yellow,
	  '{': pico.yellow,
	  '}': pico.yellow,
	  'at-word': pico.cyan,
	  'brackets': pico.cyan,
	  'call': pico.cyan,
	  'class': pico.yellow,
	  'comment': pico.gray,
	  'hash': pico.magenta,
	  'string': pico.green
	};

	function getTokenType([type, value], processor) {
	  if (type === 'word') {
	    if (value[0] === '.') {
	      return 'class'
	    }
	    if (value[0] === '#') {
	      return 'hash'
	    }
	  }

	  if (!processor.endOfFile()) {
	    let next = processor.nextToken();
	    processor.back(next);
	    if (next[0] === 'brackets' || next[0] === '(') return 'call'
	  }

	  return type
	}

	function terminalHighlight(css) {
	  let processor = tokenizer(new Input(css), { ignoreErrors: true });
	  let result = '';
	  while (!processor.endOfFile()) {
	    let token = processor.nextToken();
	    let color = HIGHLIGHT_THEME[getTokenType(token, processor)];
	    if (color) {
	      result += token[1]
	        .split(/\r?\n/)
	        .map(i => color(i))
	        .join('\n');
	    } else {
	      result += token[1];
	    }
	  }
	  return result
	}

	terminalHighlight.registerInput = registerInput;

	terminalHighlight_1 = terminalHighlight;
	return terminalHighlight_1;
}

var cssSyntaxError;
var hasRequiredCssSyntaxError;

function requireCssSyntaxError () {
	if (hasRequiredCssSyntaxError) return cssSyntaxError;
	hasRequiredCssSyntaxError = 1;

	let pico = requirePicocolors();

	let terminalHighlight = requireTerminalHighlight();

	class CssSyntaxError extends Error {
	  constructor(message, line, column, source, file, plugin) {
	    super(message);
	    this.name = 'CssSyntaxError';
	    this.reason = message;

	    if (file) {
	      this.file = file;
	    }
	    if (source) {
	      this.source = source;
	    }
	    if (plugin) {
	      this.plugin = plugin;
	    }
	    if (typeof line !== 'undefined' && typeof column !== 'undefined') {
	      if (typeof line === 'number') {
	        this.line = line;
	        this.column = column;
	      } else {
	        this.line = line.line;
	        this.column = line.column;
	        this.endLine = column.line;
	        this.endColumn = column.column;
	      }
	    }

	    this.setMessage();

	    if (Error.captureStackTrace) {
	      Error.captureStackTrace(this, CssSyntaxError);
	    }
	  }

	  setMessage() {
	    this.message = this.plugin ? this.plugin + ': ' : '';
	    this.message += this.file ? this.file : '<css input>';
	    if (typeof this.line !== 'undefined') {
	      this.message += ':' + this.line + ':' + this.column;
	    }
	    this.message += ': ' + this.reason;
	  }

	  showSourceCode(color) {
	    if (!this.source) return ''

	    let css = this.source;
	    if (color == null) color = pico.isColorSupported;
	    if (terminalHighlight) {
	      if (color) css = terminalHighlight(css);
	    }

	    let lines = css.split(/\r?\n/);
	    let start = Math.max(this.line - 3, 0);
	    let end = Math.min(this.line + 2, lines.length);

	    let maxWidth = String(end).length;

	    let mark, aside;
	    if (color) {
	      let { bold, gray, red } = pico.createColors(true);
	      mark = text => bold(red(text));
	      aside = text => gray(text);
	    } else {
	      mark = aside = str => str;
	    }

	    return lines
	      .slice(start, end)
	      .map((line, index) => {
	        let number = start + 1 + index;
	        let gutter = ' ' + (' ' + number).slice(-maxWidth) + ' | ';
	        if (number === this.line) {
	          let spacing =
	            aside(gutter.replace(/\d/g, ' ')) +
	            line.slice(0, this.column - 1).replace(/[^\t]/g, ' ');
	          return mark('>') + aside(gutter) + line + '\n ' + spacing + mark('^')
	        }
	        return ' ' + aside(gutter) + line
	      })
	      .join('\n')
	  }

	  toString() {
	    let code = this.showSourceCode();
	    if (code) {
	      code = '\n\n' + code + '\n';
	    }
	    return this.name + ': ' + this.message + code
	  }
	}

	cssSyntaxError = CssSyntaxError;
	CssSyntaxError.default = CssSyntaxError;
	return cssSyntaxError;
}

var symbols = {};

var hasRequiredSymbols;

function requireSymbols () {
	if (hasRequiredSymbols) return symbols;
	hasRequiredSymbols = 1;

	symbols.isClean = Symbol('isClean');

	symbols.my = Symbol('my');
	return symbols;
}

var stringifier;
var hasRequiredStringifier;

function requireStringifier () {
	if (hasRequiredStringifier) return stringifier;
	hasRequiredStringifier = 1;

	const DEFAULT_RAW = {
	  after: '\n',
	  beforeClose: '\n',
	  beforeComment: '\n',
	  beforeDecl: '\n',
	  beforeOpen: ' ',
	  beforeRule: '\n',
	  colon: ': ',
	  commentLeft: ' ',
	  commentRight: ' ',
	  emptyBody: '',
	  indent: '    ',
	  semicolon: false
	};

	function capitalize(str) {
	  return str[0].toUpperCase() + str.slice(1)
	}

	class Stringifier {
	  constructor(builder) {
	    this.builder = builder;
	  }

	  atrule(node, semicolon) {
	    let name = '@' + node.name;
	    let params = node.params ? this.rawValue(node, 'params') : '';

	    if (typeof node.raws.afterName !== 'undefined') {
	      name += node.raws.afterName;
	    } else if (params) {
	      name += ' ';
	    }

	    if (node.nodes) {
	      this.block(node, name + params);
	    } else {
	      let end = (node.raws.between || '') + (semicolon ? ';' : '');
	      this.builder(name + params + end, node);
	    }
	  }

	  beforeAfter(node, detect) {
	    let value;
	    if (node.type === 'decl') {
	      value = this.raw(node, null, 'beforeDecl');
	    } else if (node.type === 'comment') {
	      value = this.raw(node, null, 'beforeComment');
	    } else if (detect === 'before') {
	      value = this.raw(node, null, 'beforeRule');
	    } else {
	      value = this.raw(node, null, 'beforeClose');
	    }

	    let buf = node.parent;
	    let depth = 0;
	    while (buf && buf.type !== 'root') {
	      depth += 1;
	      buf = buf.parent;
	    }

	    if (value.includes('\n')) {
	      let indent = this.raw(node, null, 'indent');
	      if (indent.length) {
	        for (let step = 0; step < depth; step++) value += indent;
	      }
	    }

	    return value
	  }

	  block(node, start) {
	    let between = this.raw(node, 'between', 'beforeOpen');
	    this.builder(start + between + '{', node, 'start');

	    let after;
	    if (node.nodes && node.nodes.length) {
	      this.body(node);
	      after = this.raw(node, 'after');
	    } else {
	      after = this.raw(node, 'after', 'emptyBody');
	    }

	    if (after) this.builder(after);
	    this.builder('}', node, 'end');
	  }

	  body(node) {
	    let last = node.nodes.length - 1;
	    while (last > 0) {
	      if (node.nodes[last].type !== 'comment') break
	      last -= 1;
	    }

	    let semicolon = this.raw(node, 'semicolon');
	    for (let i = 0; i < node.nodes.length; i++) {
	      let child = node.nodes[i];
	      let before = this.raw(child, 'before');
	      if (before) this.builder(before);
	      this.stringify(child, last !== i || semicolon);
	    }
	  }

	  comment(node) {
	    let left = this.raw(node, 'left', 'commentLeft');
	    let right = this.raw(node, 'right', 'commentRight');
	    this.builder('/*' + left + node.text + right + '*/', node);
	  }

	  decl(node, semicolon) {
	    let between = this.raw(node, 'between', 'colon');
	    let string = node.prop + between + this.rawValue(node, 'value');

	    if (node.important) {
	      string += node.raws.important || ' !important';
	    }

	    if (semicolon) string += ';';
	    this.builder(string, node);
	  }

	  document(node) {
	    this.body(node);
	  }

	  raw(node, own, detect) {
	    let value;
	    if (!detect) detect = own;

	    // Already had
	    if (own) {
	      value = node.raws[own];
	      if (typeof value !== 'undefined') return value
	    }

	    let parent = node.parent;

	    if (detect === 'before') {
	      // Hack for first rule in CSS
	      if (!parent || (parent.type === 'root' && parent.first === node)) {
	        return ''
	      }

	      // `root` nodes in `document` should use only their own raws
	      if (parent && parent.type === 'document') {
	        return ''
	      }
	    }

	    // Floating child without parent
	    if (!parent) return DEFAULT_RAW[detect]

	    // Detect style by other nodes
	    let root = node.root();
	    if (!root.rawCache) root.rawCache = {};
	    if (typeof root.rawCache[detect] !== 'undefined') {
	      return root.rawCache[detect]
	    }

	    if (detect === 'before' || detect === 'after') {
	      return this.beforeAfter(node, detect)
	    } else {
	      let method = 'raw' + capitalize(detect);
	      if (this[method]) {
	        value = this[method](root, node);
	      } else {
	        root.walk(i => {
	          value = i.raws[own];
	          if (typeof value !== 'undefined') return false
	        });
	      }
	    }

	    if (typeof value === 'undefined') value = DEFAULT_RAW[detect];

	    root.rawCache[detect] = value;
	    return value
	  }

	  rawBeforeClose(root) {
	    let value;
	    root.walk(i => {
	      if (i.nodes && i.nodes.length > 0) {
	        if (typeof i.raws.after !== 'undefined') {
	          value = i.raws.after;
	          if (value.includes('\n')) {
	            value = value.replace(/[^\n]+$/, '');
	          }
	          return false
	        }
	      }
	    });
	    if (value) value = value.replace(/\S/g, '');
	    return value
	  }

	  rawBeforeComment(root, node) {
	    let value;
	    root.walkComments(i => {
	      if (typeof i.raws.before !== 'undefined') {
	        value = i.raws.before;
	        if (value.includes('\n')) {
	          value = value.replace(/[^\n]+$/, '');
	        }
	        return false
	      }
	    });
	    if (typeof value === 'undefined') {
	      value = this.raw(node, null, 'beforeDecl');
	    } else if (value) {
	      value = value.replace(/\S/g, '');
	    }
	    return value
	  }

	  rawBeforeDecl(root, node) {
	    let value;
	    root.walkDecls(i => {
	      if (typeof i.raws.before !== 'undefined') {
	        value = i.raws.before;
	        if (value.includes('\n')) {
	          value = value.replace(/[^\n]+$/, '');
	        }
	        return false
	      }
	    });
	    if (typeof value === 'undefined') {
	      value = this.raw(node, null, 'beforeRule');
	    } else if (value) {
	      value = value.replace(/\S/g, '');
	    }
	    return value
	  }

	  rawBeforeOpen(root) {
	    let value;
	    root.walk(i => {
	      if (i.type !== 'decl') {
	        value = i.raws.between;
	        if (typeof value !== 'undefined') return false
	      }
	    });
	    return value
	  }

	  rawBeforeRule(root) {
	    let value;
	    root.walk(i => {
	      if (i.nodes && (i.parent !== root || root.first !== i)) {
	        if (typeof i.raws.before !== 'undefined') {
	          value = i.raws.before;
	          if (value.includes('\n')) {
	            value = value.replace(/[^\n]+$/, '');
	          }
	          return false
	        }
	      }
	    });
	    if (value) value = value.replace(/\S/g, '');
	    return value
	  }

	  rawColon(root) {
	    let value;
	    root.walkDecls(i => {
	      if (typeof i.raws.between !== 'undefined') {
	        value = i.raws.between.replace(/[^\s:]/g, '');
	        return false
	      }
	    });
	    return value
	  }

	  rawEmptyBody(root) {
	    let value;
	    root.walk(i => {
	      if (i.nodes && i.nodes.length === 0) {
	        value = i.raws.after;
	        if (typeof value !== 'undefined') return false
	      }
	    });
	    return value
	  }

	  rawIndent(root) {
	    if (root.raws.indent) return root.raws.indent
	    let value;
	    root.walk(i => {
	      let p = i.parent;
	      if (p && p !== root && p.parent && p.parent === root) {
	        if (typeof i.raws.before !== 'undefined') {
	          let parts = i.raws.before.split('\n');
	          value = parts[parts.length - 1];
	          value = value.replace(/\S/g, '');
	          return false
	        }
	      }
	    });
	    return value
	  }

	  rawSemicolon(root) {
	    let value;
	    root.walk(i => {
	      if (i.nodes && i.nodes.length && i.last.type === 'decl') {
	        value = i.raws.semicolon;
	        if (typeof value !== 'undefined') return false
	      }
	    });
	    return value
	  }

	  rawValue(node, prop) {
	    let value = node[prop];
	    let raw = node.raws[prop];
	    if (raw && raw.value === value) {
	      return raw.raw
	    }

	    return value
	  }

	  root(node) {
	    this.body(node);
	    if (node.raws.after) this.builder(node.raws.after);
	  }

	  rule(node) {
	    this.block(node, this.rawValue(node, 'selector'));
	    if (node.raws.ownSemicolon) {
	      this.builder(node.raws.ownSemicolon, node, 'end');
	    }
	  }

	  stringify(node, semicolon) {
	    /* c8 ignore start */
	    if (!this[node.type]) {
	      throw new Error(
	        'Unknown AST node type ' +
	          node.type +
	          '. ' +
	          'Maybe you need to change PostCSS stringifier.'
	      )
	    }
	    /* c8 ignore stop */
	    this[node.type](node, semicolon);
	  }
	}

	stringifier = Stringifier;
	Stringifier.default = Stringifier;
	return stringifier;
}

var stringify_1;
var hasRequiredStringify;

function requireStringify () {
	if (hasRequiredStringify) return stringify_1;
	hasRequiredStringify = 1;

	let Stringifier = requireStringifier();

	function stringify(node, builder) {
	  let str = new Stringifier(builder);
	  str.stringify(node);
	}

	stringify_1 = stringify;
	stringify.default = stringify;
	return stringify_1;
}

var node;
var hasRequiredNode;

function requireNode () {
	if (hasRequiredNode) return node;
	hasRequiredNode = 1;

	let { isClean, my } = requireSymbols();
	let CssSyntaxError = requireCssSyntaxError();
	let Stringifier = requireStringifier();
	let stringify = requireStringify();

	function cloneNode(obj, parent) {
	  let cloned = new obj.constructor();

	  for (let i in obj) {
	    if (!Object.prototype.hasOwnProperty.call(obj, i)) {
	      /* c8 ignore next 2 */
	      continue
	    }
	    if (i === 'proxyCache') continue
	    let value = obj[i];
	    let type = typeof value;

	    if (i === 'parent' && type === 'object') {
	      if (parent) cloned[i] = parent;
	    } else if (i === 'source') {
	      cloned[i] = value;
	    } else if (Array.isArray(value)) {
	      cloned[i] = value.map(j => cloneNode(j, cloned));
	    } else {
	      if (type === 'object' && value !== null) value = cloneNode(value);
	      cloned[i] = value;
	    }
	  }

	  return cloned
	}

	class Node {
	  constructor(defaults = {}) {
	    this.raws = {};
	    this[isClean] = false;
	    this[my] = true;

	    for (let name in defaults) {
	      if (name === 'nodes') {
	        this.nodes = [];
	        for (let node of defaults[name]) {
	          if (typeof node.clone === 'function') {
	            this.append(node.clone());
	          } else {
	            this.append(node);
	          }
	        }
	      } else {
	        this[name] = defaults[name];
	      }
	    }
	  }

	  addToError(error) {
	    error.postcssNode = this;
	    if (error.stack && this.source && /\n\s{4}at /.test(error.stack)) {
	      let s = this.source;
	      error.stack = error.stack.replace(
	        /\n\s{4}at /,
	        `$&${s.input.from}:${s.start.line}:${s.start.column}$&`
	      );
	    }
	    return error
	  }

	  after(add) {
	    this.parent.insertAfter(this, add);
	    return this
	  }

	  assign(overrides = {}) {
	    for (let name in overrides) {
	      this[name] = overrides[name];
	    }
	    return this
	  }

	  before(add) {
	    this.parent.insertBefore(this, add);
	    return this
	  }

	  cleanRaws(keepBetween) {
	    delete this.raws.before;
	    delete this.raws.after;
	    if (!keepBetween) delete this.raws.between;
	  }

	  clone(overrides = {}) {
	    let cloned = cloneNode(this);
	    for (let name in overrides) {
	      cloned[name] = overrides[name];
	    }
	    return cloned
	  }

	  cloneAfter(overrides = {}) {
	    let cloned = this.clone(overrides);
	    this.parent.insertAfter(this, cloned);
	    return cloned
	  }

	  cloneBefore(overrides = {}) {
	    let cloned = this.clone(overrides);
	    this.parent.insertBefore(this, cloned);
	    return cloned
	  }

	  error(message, opts = {}) {
	    if (this.source) {
	      let { end, start } = this.rangeBy(opts);
	      return this.source.input.error(
	        message,
	        { column: start.column, line: start.line },
	        { column: end.column, line: end.line },
	        opts
	      )
	    }
	    return new CssSyntaxError(message)
	  }

	  getProxyProcessor() {
	    return {
	      get(node, prop) {
	        if (prop === 'proxyOf') {
	          return node
	        } else if (prop === 'root') {
	          return () => node.root().toProxy()
	        } else {
	          return node[prop]
	        }
	      },

	      set(node, prop, value) {
	        if (node[prop] === value) return true
	        node[prop] = value;
	        if (
	          prop === 'prop' ||
	          prop === 'value' ||
	          prop === 'name' ||
	          prop === 'params' ||
	          prop === 'important' ||
	          /* c8 ignore next */
	          prop === 'text'
	        ) {
	          node.markDirty();
	        }
	        return true
	      }
	    }
	  }

	  markDirty() {
	    if (this[isClean]) {
	      this[isClean] = false;
	      let next = this;
	      while ((next = next.parent)) {
	        next[isClean] = false;
	      }
	    }
	  }

	  next() {
	    if (!this.parent) return undefined
	    let index = this.parent.index(this);
	    return this.parent.nodes[index + 1]
	  }

	  positionBy(opts, stringRepresentation) {
	    let pos = this.source.start;
	    if (opts.index) {
	      pos = this.positionInside(opts.index, stringRepresentation);
	    } else if (opts.word) {
	      stringRepresentation = this.toString();
	      let index = stringRepresentation.indexOf(opts.word);
	      if (index !== -1) pos = this.positionInside(index, stringRepresentation);
	    }
	    return pos
	  }

	  positionInside(index, stringRepresentation) {
	    let string = stringRepresentation || this.toString();
	    let column = this.source.start.column;
	    let line = this.source.start.line;

	    for (let i = 0; i < index; i++) {
	      if (string[i] === '\n') {
	        column = 1;
	        line += 1;
	      } else {
	        column += 1;
	      }
	    }

	    return { column, line }
	  }

	  prev() {
	    if (!this.parent) return undefined
	    let index = this.parent.index(this);
	    return this.parent.nodes[index - 1]
	  }

	  rangeBy(opts) {
	    let start = {
	      column: this.source.start.column,
	      line: this.source.start.line
	    };
	    let end = this.source.end
	      ? {
	        column: this.source.end.column + 1,
	        line: this.source.end.line
	      }
	      : {
	        column: start.column + 1,
	        line: start.line
	      };

	    if (opts.word) {
	      let stringRepresentation = this.toString();
	      let index = stringRepresentation.indexOf(opts.word);
	      if (index !== -1) {
	        start = this.positionInside(index, stringRepresentation);
	        end = this.positionInside(index + opts.word.length, stringRepresentation);
	      }
	    } else {
	      if (opts.start) {
	        start = {
	          column: opts.start.column,
	          line: opts.start.line
	        };
	      } else if (opts.index) {
	        start = this.positionInside(opts.index);
	      }

	      if (opts.end) {
	        end = {
	          column: opts.end.column,
	          line: opts.end.line
	        };
	      } else if (typeof opts.endIndex === 'number') {
	        end = this.positionInside(opts.endIndex);
	      } else if (opts.index) {
	        end = this.positionInside(opts.index + 1);
	      }
	    }

	    if (
	      end.line < start.line ||
	      (end.line === start.line && end.column <= start.column)
	    ) {
	      end = { column: start.column + 1, line: start.line };
	    }

	    return { end, start }
	  }

	  raw(prop, defaultType) {
	    let str = new Stringifier();
	    return str.raw(this, prop, defaultType)
	  }

	  remove() {
	    if (this.parent) {
	      this.parent.removeChild(this);
	    }
	    this.parent = undefined;
	    return this
	  }

	  replaceWith(...nodes) {
	    if (this.parent) {
	      let bookmark = this;
	      let foundSelf = false;
	      for (let node of nodes) {
	        if (node === this) {
	          foundSelf = true;
	        } else if (foundSelf) {
	          this.parent.insertAfter(bookmark, node);
	          bookmark = node;
	        } else {
	          this.parent.insertBefore(bookmark, node);
	        }
	      }

	      if (!foundSelf) {
	        this.remove();
	      }
	    }

	    return this
	  }

	  root() {
	    let result = this;
	    while (result.parent && result.parent.type !== 'document') {
	      result = result.parent;
	    }
	    return result
	  }

	  toJSON(_, inputs) {
	    let fixed = {};
	    let emitInputs = inputs == null;
	    inputs = inputs || new Map();
	    let inputsNextIndex = 0;

	    for (let name in this) {
	      if (!Object.prototype.hasOwnProperty.call(this, name)) {
	        /* c8 ignore next 2 */
	        continue
	      }
	      if (name === 'parent' || name === 'proxyCache') continue
	      let value = this[name];

	      if (Array.isArray(value)) {
	        fixed[name] = value.map(i => {
	          if (typeof i === 'object' && i.toJSON) {
	            return i.toJSON(null, inputs)
	          } else {
	            return i
	          }
	        });
	      } else if (typeof value === 'object' && value.toJSON) {
	        fixed[name] = value.toJSON(null, inputs);
	      } else if (name === 'source') {
	        let inputId = inputs.get(value.input);
	        if (inputId == null) {
	          inputId = inputsNextIndex;
	          inputs.set(value.input, inputsNextIndex);
	          inputsNextIndex++;
	        }
	        fixed[name] = {
	          end: value.end,
	          inputId,
	          start: value.start
	        };
	      } else {
	        fixed[name] = value;
	      }
	    }

	    if (emitInputs) {
	      fixed.inputs = [...inputs.keys()].map(input => input.toJSON());
	    }

	    return fixed
	  }

	  toProxy() {
	    if (!this.proxyCache) {
	      this.proxyCache = new Proxy(this, this.getProxyProcessor());
	    }
	    return this.proxyCache
	  }

	  toString(stringifier = stringify) {
	    if (stringifier.stringify) stringifier = stringifier.stringify;
	    let result = '';
	    stringifier(this, i => {
	      result += i;
	    });
	    return result
	  }

	  warn(result, text, opts) {
	    let data = { node: this };
	    for (let i in opts) data[i] = opts[i];
	    return result.warn(text, data)
	  }

	  get proxyOf() {
	    return this
	  }
	}

	node = Node;
	Node.default = Node;
	return node;
}

var declaration;
var hasRequiredDeclaration;

function requireDeclaration () {
	if (hasRequiredDeclaration) return declaration;
	hasRequiredDeclaration = 1;

	let Node = requireNode();

	class Declaration extends Node {
	  constructor(defaults) {
	    if (
	      defaults &&
	      typeof defaults.value !== 'undefined' &&
	      typeof defaults.value !== 'string'
	    ) {
	      defaults = { ...defaults, value: String(defaults.value) };
	    }
	    super(defaults);
	    this.type = 'decl';
	  }

	  get variable() {
	    return this.prop.startsWith('--') || this.prop[0] === '$'
	  }
	}

	declaration = Declaration;
	Declaration.default = Declaration;
	return declaration;
}

var sourceMap = {};

var sourceMapGenerator = {};

var base64Vlq = {};

var base64 = {};

/* -*- Mode: js; js-indent-level: 2; -*- */

var hasRequiredBase64;

function requireBase64 () {
	if (hasRequiredBase64) return base64;
	hasRequiredBase64 = 1;
	/*
	 * Copyright 2011 Mozilla Foundation and contributors
	 * Licensed under the New BSD license. See LICENSE or:
	 * http://opensource.org/licenses/BSD-3-Clause
	 */

	var intToCharMap = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/'.split('');

	/**
	 * Encode an integer in the range of 0 to 63 to a single base 64 digit.
	 */
	base64.encode = function (number) {
	  if (0 <= number && number < intToCharMap.length) {
	    return intToCharMap[number];
	  }
	  throw new TypeError("Must be between 0 and 63: " + number);
	};

	/**
	 * Decode a single base 64 character code digit to an integer. Returns -1 on
	 * failure.
	 */
	base64.decode = function (charCode) {
	  var bigA = 65;     // 'A'
	  var bigZ = 90;     // 'Z'

	  var littleA = 97;  // 'a'
	  var littleZ = 122; // 'z'

	  var zero = 48;     // '0'
	  var nine = 57;     // '9'

	  var plus = 43;     // '+'
	  var slash = 47;    // '/'

	  var littleOffset = 26;
	  var numberOffset = 52;

	  // 0 - 25: ABCDEFGHIJKLMNOPQRSTUVWXYZ
	  if (bigA <= charCode && charCode <= bigZ) {
	    return (charCode - bigA);
	  }

	  // 26 - 51: abcdefghijklmnopqrstuvwxyz
	  if (littleA <= charCode && charCode <= littleZ) {
	    return (charCode - littleA + littleOffset);
	  }

	  // 52 - 61: 0123456789
	  if (zero <= charCode && charCode <= nine) {
	    return (charCode - zero + numberOffset);
	  }

	  // 62: +
	  if (charCode == plus) {
	    return 62;
	  }

	  // 63: /
	  if (charCode == slash) {
	    return 63;
	  }

	  // Invalid base64 digit.
	  return -1;
	};
	return base64;
}

/* -*- Mode: js; js-indent-level: 2; -*- */

var hasRequiredBase64Vlq;

function requireBase64Vlq () {
	if (hasRequiredBase64Vlq) return base64Vlq;
	hasRequiredBase64Vlq = 1;
	/*
	 * Copyright 2011 Mozilla Foundation and contributors
	 * Licensed under the New BSD license. See LICENSE or:
	 * http://opensource.org/licenses/BSD-3-Clause
	 *
	 * Based on the Base 64 VLQ implementation in Closure Compiler:
	 * https://code.google.com/p/closure-compiler/source/browse/trunk/src/com/google/debugging/sourcemap/Base64VLQ.java
	 *
	 * Copyright 2011 The Closure Compiler Authors. All rights reserved.
	 * Redistribution and use in source and binary forms, with or without
	 * modification, are permitted provided that the following conditions are
	 * met:
	 *
	 *  * Redistributions of source code must retain the above copyright
	 *    notice, this list of conditions and the following disclaimer.
	 *  * Redistributions in binary form must reproduce the above
	 *    copyright notice, this list of conditions and the following
	 *    disclaimer in the documentation and/or other materials provided
	 *    with the distribution.
	 *  * Neither the name of Google Inc. nor the names of its
	 *    contributors may be used to endorse or promote products derived
	 *    from this software without specific prior written permission.
	 *
	 * THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
	 * "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
	 * LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR
	 * A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT
	 * OWNER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
	 * SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT
	 * LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE,
	 * DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY
	 * THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
	 * (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
	 * OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
	 */

	var base64 = requireBase64();

	// A single base 64 digit can contain 6 bits of data. For the base 64 variable
	// length quantities we use in the source map spec, the first bit is the sign,
	// the next four bits are the actual value, and the 6th bit is the
	// continuation bit. The continuation bit tells us whether there are more
	// digits in this value following this digit.
	//
	//   Continuation
	//   |    Sign
	//   |    |
	//   V    V
	//   101011

	var VLQ_BASE_SHIFT = 5;

	// binary: 100000
	var VLQ_BASE = 1 << VLQ_BASE_SHIFT;

	// binary: 011111
	var VLQ_BASE_MASK = VLQ_BASE - 1;

	// binary: 100000
	var VLQ_CONTINUATION_BIT = VLQ_BASE;

	/**
	 * Converts from a two-complement value to a value where the sign bit is
	 * placed in the least significant bit.  For example, as decimals:
	 *   1 becomes 2 (10 binary), -1 becomes 3 (11 binary)
	 *   2 becomes 4 (100 binary), -2 becomes 5 (101 binary)
	 */
	function toVLQSigned(aValue) {
	  return aValue < 0
	    ? ((-aValue) << 1) + 1
	    : (aValue << 1) + 0;
	}

	/**
	 * Converts to a two-complement value from a value where the sign bit is
	 * placed in the least significant bit.  For example, as decimals:
	 *   2 (10 binary) becomes 1, 3 (11 binary) becomes -1
	 *   4 (100 binary) becomes 2, 5 (101 binary) becomes -2
	 */
	function fromVLQSigned(aValue) {
	  var isNegative = (aValue & 1) === 1;
	  var shifted = aValue >> 1;
	  return isNegative
	    ? -shifted
	    : shifted;
	}

	/**
	 * Returns the base 64 VLQ encoded value.
	 */
	base64Vlq.encode = function base64VLQ_encode(aValue) {
	  var encoded = "";
	  var digit;

	  var vlq = toVLQSigned(aValue);

	  do {
	    digit = vlq & VLQ_BASE_MASK;
	    vlq >>>= VLQ_BASE_SHIFT;
	    if (vlq > 0) {
	      // There are still more digits in this value, so we must make sure the
	      // continuation bit is marked.
	      digit |= VLQ_CONTINUATION_BIT;
	    }
	    encoded += base64.encode(digit);
	  } while (vlq > 0);

	  return encoded;
	};

	/**
	 * Decodes the next base 64 VLQ value from the given string and returns the
	 * value and the rest of the string via the out parameter.
	 */
	base64Vlq.decode = function base64VLQ_decode(aStr, aIndex, aOutParam) {
	  var strLen = aStr.length;
	  var result = 0;
	  var shift = 0;
	  var continuation, digit;

	  do {
	    if (aIndex >= strLen) {
	      throw new Error("Expected more digits in base 64 VLQ value.");
	    }

	    digit = base64.decode(aStr.charCodeAt(aIndex++));
	    if (digit === -1) {
	      throw new Error("Invalid base64 digit: " + aStr.charAt(aIndex - 1));
	    }

	    continuation = !!(digit & VLQ_CONTINUATION_BIT);
	    digit &= VLQ_BASE_MASK;
	    result = result + (digit << shift);
	    shift += VLQ_BASE_SHIFT;
	  } while (continuation);

	  aOutParam.value = fromVLQSigned(result);
	  aOutParam.rest = aIndex;
	};
	return base64Vlq;
}

var util = {};

/* -*- Mode: js; js-indent-level: 2; -*- */

var hasRequiredUtil;

function requireUtil () {
	if (hasRequiredUtil) return util;
	hasRequiredUtil = 1;
	(function (exports) {
		/*
		 * Copyright 2011 Mozilla Foundation and contributors
		 * Licensed under the New BSD license. See LICENSE or:
		 * http://opensource.org/licenses/BSD-3-Clause
		 */

		/**
		 * This is a helper function for getting values from parameter/options
		 * objects.
		 *
		 * @param args The object we are extracting values from
		 * @param name The name of the property we are getting.
		 * @param defaultValue An optional value to return if the property is missing
		 * from the object. If this is not specified and the property is missing, an
		 * error will be thrown.
		 */
		function getArg(aArgs, aName, aDefaultValue) {
		  if (aName in aArgs) {
		    return aArgs[aName];
		  } else if (arguments.length === 3) {
		    return aDefaultValue;
		  } else {
		    throw new Error('"' + aName + '" is a required argument.');
		  }
		}
		exports.getArg = getArg;

		var urlRegexp = /^(?:([\w+\-.]+):)?\/\/(?:(\w+:\w+)@)?([\w.-]*)(?::(\d+))?(.*)$/;
		var dataUrlRegexp = /^data:.+\,.+$/;

		function urlParse(aUrl) {
		  var match = aUrl.match(urlRegexp);
		  if (!match) {
		    return null;
		  }
		  return {
		    scheme: match[1],
		    auth: match[2],
		    host: match[3],
		    port: match[4],
		    path: match[5]
		  };
		}
		exports.urlParse = urlParse;

		function urlGenerate(aParsedUrl) {
		  var url = '';
		  if (aParsedUrl.scheme) {
		    url += aParsedUrl.scheme + ':';
		  }
		  url += '//';
		  if (aParsedUrl.auth) {
		    url += aParsedUrl.auth + '@';
		  }
		  if (aParsedUrl.host) {
		    url += aParsedUrl.host;
		  }
		  if (aParsedUrl.port) {
		    url += ":" + aParsedUrl.port;
		  }
		  if (aParsedUrl.path) {
		    url += aParsedUrl.path;
		  }
		  return url;
		}
		exports.urlGenerate = urlGenerate;

		var MAX_CACHED_INPUTS = 32;

		/**
		 * Takes some function `f(input) -> result` and returns a memoized version of
		 * `f`.
		 *
		 * We keep at most `MAX_CACHED_INPUTS` memoized results of `f` alive. The
		 * memoization is a dumb-simple, linear least-recently-used cache.
		 */
		function lruMemoize(f) {
		  var cache = [];

		  return function(input) {
		    for (var i = 0; i < cache.length; i++) {
		      if (cache[i].input === input) {
		        var temp = cache[0];
		        cache[0] = cache[i];
		        cache[i] = temp;
		        return cache[0].result;
		      }
		    }

		    var result = f(input);

		    cache.unshift({
		      input,
		      result,
		    });

		    if (cache.length > MAX_CACHED_INPUTS) {
		      cache.pop();
		    }

		    return result;
		  };
		}

		/**
		 * Normalizes a path, or the path portion of a URL:
		 *
		 * - Replaces consecutive slashes with one slash.
		 * - Removes unnecessary '.' parts.
		 * - Removes unnecessary '<dir>/..' parts.
		 *
		 * Based on code in the Node.js 'path' core module.
		 *
		 * @param aPath The path or url to normalize.
		 */
		var normalize = lruMemoize(function normalize(aPath) {
		  var path = aPath;
		  var url = urlParse(aPath);
		  if (url) {
		    if (!url.path) {
		      return aPath;
		    }
		    path = url.path;
		  }
		  var isAbsolute = exports.isAbsolute(path);
		  // Split the path into parts between `/` characters. This is much faster than
		  // using `.split(/\/+/g)`.
		  var parts = [];
		  var start = 0;
		  var i = 0;
		  while (true) {
		    start = i;
		    i = path.indexOf("/", start);
		    if (i === -1) {
		      parts.push(path.slice(start));
		      break;
		    } else {
		      parts.push(path.slice(start, i));
		      while (i < path.length && path[i] === "/") {
		        i++;
		      }
		    }
		  }

		  for (var part, up = 0, i = parts.length - 1; i >= 0; i--) {
		    part = parts[i];
		    if (part === '.') {
		      parts.splice(i, 1);
		    } else if (part === '..') {
		      up++;
		    } else if (up > 0) {
		      if (part === '') {
		        // The first part is blank if the path is absolute. Trying to go
		        // above the root is a no-op. Therefore we can remove all '..' parts
		        // directly after the root.
		        parts.splice(i + 1, up);
		        up = 0;
		      } else {
		        parts.splice(i, 2);
		        up--;
		      }
		    }
		  }
		  path = parts.join('/');

		  if (path === '') {
		    path = isAbsolute ? '/' : '.';
		  }

		  if (url) {
		    url.path = path;
		    return urlGenerate(url);
		  }
		  return path;
		});
		exports.normalize = normalize;

		/**
		 * Joins two paths/URLs.
		 *
		 * @param aRoot The root path or URL.
		 * @param aPath The path or URL to be joined with the root.
		 *
		 * - If aPath is a URL or a data URI, aPath is returned, unless aPath is a
		 *   scheme-relative URL: Then the scheme of aRoot, if any, is prepended
		 *   first.
		 * - Otherwise aPath is a path. If aRoot is a URL, then its path portion
		 *   is updated with the result and aRoot is returned. Otherwise the result
		 *   is returned.
		 *   - If aPath is absolute, the result is aPath.
		 *   - Otherwise the two paths are joined with a slash.
		 * - Joining for example 'http://' and 'www.example.com' is also supported.
		 */
		function join(aRoot, aPath) {
		  if (aRoot === "") {
		    aRoot = ".";
		  }
		  if (aPath === "") {
		    aPath = ".";
		  }
		  var aPathUrl = urlParse(aPath);
		  var aRootUrl = urlParse(aRoot);
		  if (aRootUrl) {
		    aRoot = aRootUrl.path || '/';
		  }

		  // `join(foo, '//www.example.org')`
		  if (aPathUrl && !aPathUrl.scheme) {
		    if (aRootUrl) {
		      aPathUrl.scheme = aRootUrl.scheme;
		    }
		    return urlGenerate(aPathUrl);
		  }

		  if (aPathUrl || aPath.match(dataUrlRegexp)) {
		    return aPath;
		  }

		  // `join('http://', 'www.example.com')`
		  if (aRootUrl && !aRootUrl.host && !aRootUrl.path) {
		    aRootUrl.host = aPath;
		    return urlGenerate(aRootUrl);
		  }

		  var joined = aPath.charAt(0) === '/'
		    ? aPath
		    : normalize(aRoot.replace(/\/+$/, '') + '/' + aPath);

		  if (aRootUrl) {
		    aRootUrl.path = joined;
		    return urlGenerate(aRootUrl);
		  }
		  return joined;
		}
		exports.join = join;

		exports.isAbsolute = function (aPath) {
		  return aPath.charAt(0) === '/' || urlRegexp.test(aPath);
		};

		/**
		 * Make a path relative to a URL or another path.
		 *
		 * @param aRoot The root path or URL.
		 * @param aPath The path or URL to be made relative to aRoot.
		 */
		function relative(aRoot, aPath) {
		  if (aRoot === "") {
		    aRoot = ".";
		  }

		  aRoot = aRoot.replace(/\/$/, '');

		  // It is possible for the path to be above the root. In this case, simply
		  // checking whether the root is a prefix of the path won't work. Instead, we
		  // need to remove components from the root one by one, until either we find
		  // a prefix that fits, or we run out of components to remove.
		  var level = 0;
		  while (aPath.indexOf(aRoot + '/') !== 0) {
		    var index = aRoot.lastIndexOf("/");
		    if (index < 0) {
		      return aPath;
		    }

		    // If the only part of the root that is left is the scheme (i.e. http://,
		    // file:///, etc.), one or more slashes (/), or simply nothing at all, we
		    // have exhausted all components, so the path is not relative to the root.
		    aRoot = aRoot.slice(0, index);
		    if (aRoot.match(/^([^\/]+:\/)?\/*$/)) {
		      return aPath;
		    }

		    ++level;
		  }

		  // Make sure we add a "../" for each component we removed from the root.
		  return Array(level + 1).join("../") + aPath.substr(aRoot.length + 1);
		}
		exports.relative = relative;

		var supportsNullProto = (function () {
		  var obj = Object.create(null);
		  return !('__proto__' in obj);
		}());

		function identity (s) {
		  return s;
		}

		/**
		 * Because behavior goes wacky when you set `__proto__` on objects, we
		 * have to prefix all the strings in our set with an arbitrary character.
		 *
		 * See https://github.com/mozilla/source-map/pull/31 and
		 * https://github.com/mozilla/source-map/issues/30
		 *
		 * @param String aStr
		 */
		function toSetString(aStr) {
		  if (isProtoString(aStr)) {
		    return '$' + aStr;
		  }

		  return aStr;
		}
		exports.toSetString = supportsNullProto ? identity : toSetString;

		function fromSetString(aStr) {
		  if (isProtoString(aStr)) {
		    return aStr.slice(1);
		  }

		  return aStr;
		}
		exports.fromSetString = supportsNullProto ? identity : fromSetString;

		function isProtoString(s) {
		  if (!s) {
		    return false;
		  }

		  var length = s.length;

		  if (length < 9 /* "__proto__".length */) {
		    return false;
		  }

		  if (s.charCodeAt(length - 1) !== 95  /* '_' */ ||
		      s.charCodeAt(length - 2) !== 95  /* '_' */ ||
		      s.charCodeAt(length - 3) !== 111 /* 'o' */ ||
		      s.charCodeAt(length - 4) !== 116 /* 't' */ ||
		      s.charCodeAt(length - 5) !== 111 /* 'o' */ ||
		      s.charCodeAt(length - 6) !== 114 /* 'r' */ ||
		      s.charCodeAt(length - 7) !== 112 /* 'p' */ ||
		      s.charCodeAt(length - 8) !== 95  /* '_' */ ||
		      s.charCodeAt(length - 9) !== 95  /* '_' */) {
		    return false;
		  }

		  for (var i = length - 10; i >= 0; i--) {
		    if (s.charCodeAt(i) !== 36 /* '$' */) {
		      return false;
		    }
		  }

		  return true;
		}

		/**
		 * Comparator between two mappings where the original positions are compared.
		 *
		 * Optionally pass in `true` as `onlyCompareGenerated` to consider two
		 * mappings with the same original source/line/column, but different generated
		 * line and column the same. Useful when searching for a mapping with a
		 * stubbed out mapping.
		 */
		function compareByOriginalPositions(mappingA, mappingB, onlyCompareOriginal) {
		  var cmp = strcmp(mappingA.source, mappingB.source);
		  if (cmp !== 0) {
		    return cmp;
		  }

		  cmp = mappingA.originalLine - mappingB.originalLine;
		  if (cmp !== 0) {
		    return cmp;
		  }

		  cmp = mappingA.originalColumn - mappingB.originalColumn;
		  if (cmp !== 0 || onlyCompareOriginal) {
		    return cmp;
		  }

		  cmp = mappingA.generatedColumn - mappingB.generatedColumn;
		  if (cmp !== 0) {
		    return cmp;
		  }

		  cmp = mappingA.generatedLine - mappingB.generatedLine;
		  if (cmp !== 0) {
		    return cmp;
		  }

		  return strcmp(mappingA.name, mappingB.name);
		}
		exports.compareByOriginalPositions = compareByOriginalPositions;

		function compareByOriginalPositionsNoSource(mappingA, mappingB, onlyCompareOriginal) {
		  var cmp;

		  cmp = mappingA.originalLine - mappingB.originalLine;
		  if (cmp !== 0) {
		    return cmp;
		  }

		  cmp = mappingA.originalColumn - mappingB.originalColumn;
		  if (cmp !== 0 || onlyCompareOriginal) {
		    return cmp;
		  }

		  cmp = mappingA.generatedColumn - mappingB.generatedColumn;
		  if (cmp !== 0) {
		    return cmp;
		  }

		  cmp = mappingA.generatedLine - mappingB.generatedLine;
		  if (cmp !== 0) {
		    return cmp;
		  }

		  return strcmp(mappingA.name, mappingB.name);
		}
		exports.compareByOriginalPositionsNoSource = compareByOriginalPositionsNoSource;

		/**
		 * Comparator between two mappings with deflated source and name indices where
		 * the generated positions are compared.
		 *
		 * Optionally pass in `true` as `onlyCompareGenerated` to consider two
		 * mappings with the same generated line and column, but different
		 * source/name/original line and column the same. Useful when searching for a
		 * mapping with a stubbed out mapping.
		 */
		function compareByGeneratedPositionsDeflated(mappingA, mappingB, onlyCompareGenerated) {
		  var cmp = mappingA.generatedLine - mappingB.generatedLine;
		  if (cmp !== 0) {
		    return cmp;
		  }

		  cmp = mappingA.generatedColumn - mappingB.generatedColumn;
		  if (cmp !== 0 || onlyCompareGenerated) {
		    return cmp;
		  }

		  cmp = strcmp(mappingA.source, mappingB.source);
		  if (cmp !== 0) {
		    return cmp;
		  }

		  cmp = mappingA.originalLine - mappingB.originalLine;
		  if (cmp !== 0) {
		    return cmp;
		  }

		  cmp = mappingA.originalColumn - mappingB.originalColumn;
		  if (cmp !== 0) {
		    return cmp;
		  }

		  return strcmp(mappingA.name, mappingB.name);
		}
		exports.compareByGeneratedPositionsDeflated = compareByGeneratedPositionsDeflated;

		function compareByGeneratedPositionsDeflatedNoLine(mappingA, mappingB, onlyCompareGenerated) {
		  var cmp = mappingA.generatedColumn - mappingB.generatedColumn;
		  if (cmp !== 0 || onlyCompareGenerated) {
		    return cmp;
		  }

		  cmp = strcmp(mappingA.source, mappingB.source);
		  if (cmp !== 0) {
		    return cmp;
		  }

		  cmp = mappingA.originalLine - mappingB.originalLine;
		  if (cmp !== 0) {
		    return cmp;
		  }

		  cmp = mappingA.originalColumn - mappingB.originalColumn;
		  if (cmp !== 0) {
		    return cmp;
		  }

		  return strcmp(mappingA.name, mappingB.name);
		}
		exports.compareByGeneratedPositionsDeflatedNoLine = compareByGeneratedPositionsDeflatedNoLine;

		function strcmp(aStr1, aStr2) {
		  if (aStr1 === aStr2) {
		    return 0;
		  }

		  if (aStr1 === null) {
		    return 1; // aStr2 !== null
		  }

		  if (aStr2 === null) {
		    return -1; // aStr1 !== null
		  }

		  if (aStr1 > aStr2) {
		    return 1;
		  }

		  return -1;
		}

		/**
		 * Comparator between two mappings with inflated source and name strings where
		 * the generated positions are compared.
		 */
		function compareByGeneratedPositionsInflated(mappingA, mappingB) {
		  var cmp = mappingA.generatedLine - mappingB.generatedLine;
		  if (cmp !== 0) {
		    return cmp;
		  }

		  cmp = mappingA.generatedColumn - mappingB.generatedColumn;
		  if (cmp !== 0) {
		    return cmp;
		  }

		  cmp = strcmp(mappingA.source, mappingB.source);
		  if (cmp !== 0) {
		    return cmp;
		  }

		  cmp = mappingA.originalLine - mappingB.originalLine;
		  if (cmp !== 0) {
		    return cmp;
		  }

		  cmp = mappingA.originalColumn - mappingB.originalColumn;
		  if (cmp !== 0) {
		    return cmp;
		  }

		  return strcmp(mappingA.name, mappingB.name);
		}
		exports.compareByGeneratedPositionsInflated = compareByGeneratedPositionsInflated;

		/**
		 * Strip any JSON XSSI avoidance prefix from the string (as documented
		 * in the source maps specification), and then parse the string as
		 * JSON.
		 */
		function parseSourceMapInput(str) {
		  return JSON.parse(str.replace(/^\)]}'[^\n]*\n/, ''));
		}
		exports.parseSourceMapInput = parseSourceMapInput;

		/**
		 * Compute the URL of a source given the the source root, the source's
		 * URL, and the source map's URL.
		 */
		function computeSourceURL(sourceRoot, sourceURL, sourceMapURL) {
		  sourceURL = sourceURL || '';

		  if (sourceRoot) {
		    // This follows what Chrome does.
		    if (sourceRoot[sourceRoot.length - 1] !== '/' && sourceURL[0] !== '/') {
		      sourceRoot += '/';
		    }
		    // The spec says:
		    //   Line 4: An optional source root, useful for relocating source
		    //   files on a server or removing repeated values in the
		    //   “sources” entry.  This value is prepended to the individual
		    //   entries in the “source” field.
		    sourceURL = sourceRoot + sourceURL;
		  }

		  // Historically, SourceMapConsumer did not take the sourceMapURL as
		  // a parameter.  This mode is still somewhat supported, which is why
		  // this code block is conditional.  However, it's preferable to pass
		  // the source map URL to SourceMapConsumer, so that this function
		  // can implement the source URL resolution algorithm as outlined in
		  // the spec.  This block is basically the equivalent of:
		  //    new URL(sourceURL, sourceMapURL).toString()
		  // ... except it avoids using URL, which wasn't available in the
		  // older releases of node still supported by this library.
		  //
		  // The spec says:
		  //   If the sources are not absolute URLs after prepending of the
		  //   “sourceRoot”, the sources are resolved relative to the
		  //   SourceMap (like resolving script src in a html document).
		  if (sourceMapURL) {
		    var parsed = urlParse(sourceMapURL);
		    if (!parsed) {
		      throw new Error("sourceMapURL could not be parsed");
		    }
		    if (parsed.path) {
		      // Strip the last path component, but keep the "/".
		      var index = parsed.path.lastIndexOf('/');
		      if (index >= 0) {
		        parsed.path = parsed.path.substring(0, index + 1);
		      }
		    }
		    sourceURL = join(urlGenerate(parsed), sourceURL);
		  }

		  return normalize(sourceURL);
		}
		exports.computeSourceURL = computeSourceURL; 
	} (util));
	return util;
}

var arraySet = {};

/* -*- Mode: js; js-indent-level: 2; -*- */

var hasRequiredArraySet;

function requireArraySet () {
	if (hasRequiredArraySet) return arraySet;
	hasRequiredArraySet = 1;
	/*
	 * Copyright 2011 Mozilla Foundation and contributors
	 * Licensed under the New BSD license. See LICENSE or:
	 * http://opensource.org/licenses/BSD-3-Clause
	 */

	var util = requireUtil();
	var has = Object.prototype.hasOwnProperty;
	var hasNativeMap = typeof Map !== "undefined";

	/**
	 * A data structure which is a combination of an array and a set. Adding a new
	 * member is O(1), testing for membership is O(1), and finding the index of an
	 * element is O(1). Removing elements from the set is not supported. Only
	 * strings are supported for membership.
	 */
	function ArraySet() {
	  this._array = [];
	  this._set = hasNativeMap ? new Map() : Object.create(null);
	}

	/**
	 * Static method for creating ArraySet instances from an existing array.
	 */
	ArraySet.fromArray = function ArraySet_fromArray(aArray, aAllowDuplicates) {
	  var set = new ArraySet();
	  for (var i = 0, len = aArray.length; i < len; i++) {
	    set.add(aArray[i], aAllowDuplicates);
	  }
	  return set;
	};

	/**
	 * Return how many unique items are in this ArraySet. If duplicates have been
	 * added, than those do not count towards the size.
	 *
	 * @returns Number
	 */
	ArraySet.prototype.size = function ArraySet_size() {
	  return hasNativeMap ? this._set.size : Object.getOwnPropertyNames(this._set).length;
	};

	/**
	 * Add the given string to this set.
	 *
	 * @param String aStr
	 */
	ArraySet.prototype.add = function ArraySet_add(aStr, aAllowDuplicates) {
	  var sStr = hasNativeMap ? aStr : util.toSetString(aStr);
	  var isDuplicate = hasNativeMap ? this.has(aStr) : has.call(this._set, sStr);
	  var idx = this._array.length;
	  if (!isDuplicate || aAllowDuplicates) {
	    this._array.push(aStr);
	  }
	  if (!isDuplicate) {
	    if (hasNativeMap) {
	      this._set.set(aStr, idx);
	    } else {
	      this._set[sStr] = idx;
	    }
	  }
	};

	/**
	 * Is the given string a member of this set?
	 *
	 * @param String aStr
	 */
	ArraySet.prototype.has = function ArraySet_has(aStr) {
	  if (hasNativeMap) {
	    return this._set.has(aStr);
	  } else {
	    var sStr = util.toSetString(aStr);
	    return has.call(this._set, sStr);
	  }
	};

	/**
	 * What is the index of the given string in the array?
	 *
	 * @param String aStr
	 */
	ArraySet.prototype.indexOf = function ArraySet_indexOf(aStr) {
	  if (hasNativeMap) {
	    var idx = this._set.get(aStr);
	    if (idx >= 0) {
	        return idx;
	    }
	  } else {
	    var sStr = util.toSetString(aStr);
	    if (has.call(this._set, sStr)) {
	      return this._set[sStr];
	    }
	  }

	  throw new Error('"' + aStr + '" is not in the set.');
	};

	/**
	 * What is the element at the given index?
	 *
	 * @param Number aIdx
	 */
	ArraySet.prototype.at = function ArraySet_at(aIdx) {
	  if (aIdx >= 0 && aIdx < this._array.length) {
	    return this._array[aIdx];
	  }
	  throw new Error('No element indexed by ' + aIdx);
	};

	/**
	 * Returns the array representation of this set (which has the proper indices
	 * indicated by indexOf). Note that this is a copy of the internal array used
	 * for storing the members so that no one can mess with internal state.
	 */
	ArraySet.prototype.toArray = function ArraySet_toArray() {
	  return this._array.slice();
	};

	arraySet.ArraySet = ArraySet;
	return arraySet;
}

var mappingList = {};

/* -*- Mode: js; js-indent-level: 2; -*- */

var hasRequiredMappingList;

function requireMappingList () {
	if (hasRequiredMappingList) return mappingList;
	hasRequiredMappingList = 1;
	/*
	 * Copyright 2014 Mozilla Foundation and contributors
	 * Licensed under the New BSD license. See LICENSE or:
	 * http://opensource.org/licenses/BSD-3-Clause
	 */

	var util = requireUtil();

	/**
	 * Determine whether mappingB is after mappingA with respect to generated
	 * position.
	 */
	function generatedPositionAfter(mappingA, mappingB) {
	  // Optimized for most common case
	  var lineA = mappingA.generatedLine;
	  var lineB = mappingB.generatedLine;
	  var columnA = mappingA.generatedColumn;
	  var columnB = mappingB.generatedColumn;
	  return lineB > lineA || lineB == lineA && columnB >= columnA ||
	         util.compareByGeneratedPositionsInflated(mappingA, mappingB) <= 0;
	}

	/**
	 * A data structure to provide a sorted view of accumulated mappings in a
	 * performance conscious manner. It trades a neglibable overhead in general
	 * case for a large speedup in case of mappings being added in order.
	 */
	function MappingList() {
	  this._array = [];
	  this._sorted = true;
	  // Serves as infimum
	  this._last = {generatedLine: -1, generatedColumn: 0};
	}

	/**
	 * Iterate through internal items. This method takes the same arguments that
	 * `Array.prototype.forEach` takes.
	 *
	 * NOTE: The order of the mappings is NOT guaranteed.
	 */
	MappingList.prototype.unsortedForEach =
	  function MappingList_forEach(aCallback, aThisArg) {
	    this._array.forEach(aCallback, aThisArg);
	  };

	/**
	 * Add the given source mapping.
	 *
	 * @param Object aMapping
	 */
	MappingList.prototype.add = function MappingList_add(aMapping) {
	  if (generatedPositionAfter(this._last, aMapping)) {
	    this._last = aMapping;
	    this._array.push(aMapping);
	  } else {
	    this._sorted = false;
	    this._array.push(aMapping);
	  }
	};

	/**
	 * Returns the flat, sorted array of mappings. The mappings are sorted by
	 * generated position.
	 *
	 * WARNING: This method returns internal data without copying, for
	 * performance. The return value must NOT be mutated, and should be treated as
	 * an immutable borrow. If you want to take ownership, you must make your own
	 * copy.
	 */
	MappingList.prototype.toArray = function MappingList_toArray() {
	  if (!this._sorted) {
	    this._array.sort(util.compareByGeneratedPositionsInflated);
	    this._sorted = true;
	  }
	  return this._array;
	};

	mappingList.MappingList = MappingList;
	return mappingList;
}

/* -*- Mode: js; js-indent-level: 2; -*- */

var hasRequiredSourceMapGenerator;

function requireSourceMapGenerator () {
	if (hasRequiredSourceMapGenerator) return sourceMapGenerator;
	hasRequiredSourceMapGenerator = 1;
	/*
	 * Copyright 2011 Mozilla Foundation and contributors
	 * Licensed under the New BSD license. See LICENSE or:
	 * http://opensource.org/licenses/BSD-3-Clause
	 */

	var base64VLQ = requireBase64Vlq();
	var util = requireUtil();
	var ArraySet = requireArraySet().ArraySet;
	var MappingList = requireMappingList().MappingList;

	/**
	 * An instance of the SourceMapGenerator represents a source map which is
	 * being built incrementally. You may pass an object with the following
	 * properties:
	 *
	 *   - file: The filename of the generated source.
	 *   - sourceRoot: A root for all relative URLs in this source map.
	 */
	function SourceMapGenerator(aArgs) {
	  if (!aArgs) {
	    aArgs = {};
	  }
	  this._file = util.getArg(aArgs, 'file', null);
	  this._sourceRoot = util.getArg(aArgs, 'sourceRoot', null);
	  this._skipValidation = util.getArg(aArgs, 'skipValidation', false);
	  this._ignoreInvalidMapping = util.getArg(aArgs, 'ignoreInvalidMapping', false);
	  this._sources = new ArraySet();
	  this._names = new ArraySet();
	  this._mappings = new MappingList();
	  this._sourcesContents = null;
	}

	SourceMapGenerator.prototype._version = 3;

	/**
	 * Creates a new SourceMapGenerator based on a SourceMapConsumer
	 *
	 * @param aSourceMapConsumer The SourceMap.
	 */
	SourceMapGenerator.fromSourceMap =
	  function SourceMapGenerator_fromSourceMap(aSourceMapConsumer, generatorOps) {
	    var sourceRoot = aSourceMapConsumer.sourceRoot;
	    var generator = new SourceMapGenerator(Object.assign(generatorOps || {}, {
	      file: aSourceMapConsumer.file,
	      sourceRoot: sourceRoot
	    }));
	    aSourceMapConsumer.eachMapping(function (mapping) {
	      var newMapping = {
	        generated: {
	          line: mapping.generatedLine,
	          column: mapping.generatedColumn
	        }
	      };

	      if (mapping.source != null) {
	        newMapping.source = mapping.source;
	        if (sourceRoot != null) {
	          newMapping.source = util.relative(sourceRoot, newMapping.source);
	        }

	        newMapping.original = {
	          line: mapping.originalLine,
	          column: mapping.originalColumn
	        };

	        if (mapping.name != null) {
	          newMapping.name = mapping.name;
	        }
	      }

	      generator.addMapping(newMapping);
	    });
	    aSourceMapConsumer.sources.forEach(function (sourceFile) {
	      var sourceRelative = sourceFile;
	      if (sourceRoot !== null) {
	        sourceRelative = util.relative(sourceRoot, sourceFile);
	      }

	      if (!generator._sources.has(sourceRelative)) {
	        generator._sources.add(sourceRelative);
	      }

	      var content = aSourceMapConsumer.sourceContentFor(sourceFile);
	      if (content != null) {
	        generator.setSourceContent(sourceFile, content);
	      }
	    });
	    return generator;
	  };

	/**
	 * Add a single mapping from original source line and column to the generated
	 * source's line and column for this source map being created. The mapping
	 * object should have the following properties:
	 *
	 *   - generated: An object with the generated line and column positions.
	 *   - original: An object with the original line and column positions.
	 *   - source: The original source file (relative to the sourceRoot).
	 *   - name: An optional original token name for this mapping.
	 */
	SourceMapGenerator.prototype.addMapping =
	  function SourceMapGenerator_addMapping(aArgs) {
	    var generated = util.getArg(aArgs, 'generated');
	    var original = util.getArg(aArgs, 'original', null);
	    var source = util.getArg(aArgs, 'source', null);
	    var name = util.getArg(aArgs, 'name', null);

	    if (!this._skipValidation) {
	      if (this._validateMapping(generated, original, source, name) === false) {
	        return;
	      }
	    }

	    if (source != null) {
	      source = String(source);
	      if (!this._sources.has(source)) {
	        this._sources.add(source);
	      }
	    }

	    if (name != null) {
	      name = String(name);
	      if (!this._names.has(name)) {
	        this._names.add(name);
	      }
	    }

	    this._mappings.add({
	      generatedLine: generated.line,
	      generatedColumn: generated.column,
	      originalLine: original != null && original.line,
	      originalColumn: original != null && original.column,
	      source: source,
	      name: name
	    });
	  };

	/**
	 * Set the source content for a source file.
	 */
	SourceMapGenerator.prototype.setSourceContent =
	  function SourceMapGenerator_setSourceContent(aSourceFile, aSourceContent) {
	    var source = aSourceFile;
	    if (this._sourceRoot != null) {
	      source = util.relative(this._sourceRoot, source);
	    }

	    if (aSourceContent != null) {
	      // Add the source content to the _sourcesContents map.
	      // Create a new _sourcesContents map if the property is null.
	      if (!this._sourcesContents) {
	        this._sourcesContents = Object.create(null);
	      }
	      this._sourcesContents[util.toSetString(source)] = aSourceContent;
	    } else if (this._sourcesContents) {
	      // Remove the source file from the _sourcesContents map.
	      // If the _sourcesContents map is empty, set the property to null.
	      delete this._sourcesContents[util.toSetString(source)];
	      if (Object.keys(this._sourcesContents).length === 0) {
	        this._sourcesContents = null;
	      }
	    }
	  };

	/**
	 * Applies the mappings of a sub-source-map for a specific source file to the
	 * source map being generated. Each mapping to the supplied source file is
	 * rewritten using the supplied source map. Note: The resolution for the
	 * resulting mappings is the minimium of this map and the supplied map.
	 *
	 * @param aSourceMapConsumer The source map to be applied.
	 * @param aSourceFile Optional. The filename of the source file.
	 *        If omitted, SourceMapConsumer's file property will be used.
	 * @param aSourceMapPath Optional. The dirname of the path to the source map
	 *        to be applied. If relative, it is relative to the SourceMapConsumer.
	 *        This parameter is needed when the two source maps aren't in the same
	 *        directory, and the source map to be applied contains relative source
	 *        paths. If so, those relative source paths need to be rewritten
	 *        relative to the SourceMapGenerator.
	 */
	SourceMapGenerator.prototype.applySourceMap =
	  function SourceMapGenerator_applySourceMap(aSourceMapConsumer, aSourceFile, aSourceMapPath) {
	    var sourceFile = aSourceFile;
	    // If aSourceFile is omitted, we will use the file property of the SourceMap
	    if (aSourceFile == null) {
	      if (aSourceMapConsumer.file == null) {
	        throw new Error(
	          'SourceMapGenerator.prototype.applySourceMap requires either an explicit source file, ' +
	          'or the source map\'s "file" property. Both were omitted.'
	        );
	      }
	      sourceFile = aSourceMapConsumer.file;
	    }
	    var sourceRoot = this._sourceRoot;
	    // Make "sourceFile" relative if an absolute Url is passed.
	    if (sourceRoot != null) {
	      sourceFile = util.relative(sourceRoot, sourceFile);
	    }
	    // Applying the SourceMap can add and remove items from the sources and
	    // the names array.
	    var newSources = new ArraySet();
	    var newNames = new ArraySet();

	    // Find mappings for the "sourceFile"
	    this._mappings.unsortedForEach(function (mapping) {
	      if (mapping.source === sourceFile && mapping.originalLine != null) {
	        // Check if it can be mapped by the source map, then update the mapping.
	        var original = aSourceMapConsumer.originalPositionFor({
	          line: mapping.originalLine,
	          column: mapping.originalColumn
	        });
	        if (original.source != null) {
	          // Copy mapping
	          mapping.source = original.source;
	          if (aSourceMapPath != null) {
	            mapping.source = util.join(aSourceMapPath, mapping.source);
	          }
	          if (sourceRoot != null) {
	            mapping.source = util.relative(sourceRoot, mapping.source);
	          }
	          mapping.originalLine = original.line;
	          mapping.originalColumn = original.column;
	          if (original.name != null) {
	            mapping.name = original.name;
	          }
	        }
	      }

	      var source = mapping.source;
	      if (source != null && !newSources.has(source)) {
	        newSources.add(source);
	      }

	      var name = mapping.name;
	      if (name != null && !newNames.has(name)) {
	        newNames.add(name);
	      }

	    }, this);
	    this._sources = newSources;
	    this._names = newNames;

	    // Copy sourcesContents of applied map.
	    aSourceMapConsumer.sources.forEach(function (sourceFile) {
	      var content = aSourceMapConsumer.sourceContentFor(sourceFile);
	      if (content != null) {
	        if (aSourceMapPath != null) {
	          sourceFile = util.join(aSourceMapPath, sourceFile);
	        }
	        if (sourceRoot != null) {
	          sourceFile = util.relative(sourceRoot, sourceFile);
	        }
	        this.setSourceContent(sourceFile, content);
	      }
	    }, this);
	  };

	/**
	 * A mapping can have one of the three levels of data:
	 *
	 *   1. Just the generated position.
	 *   2. The Generated position, original position, and original source.
	 *   3. Generated and original position, original source, as well as a name
	 *      token.
	 *
	 * To maintain consistency, we validate that any new mapping being added falls
	 * in to one of these categories.
	 */
	SourceMapGenerator.prototype._validateMapping =
	  function SourceMapGenerator_validateMapping(aGenerated, aOriginal, aSource,
	                                              aName) {
	    // When aOriginal is truthy but has empty values for .line and .column,
	    // it is most likely a programmer error. In this case we throw a very
	    // specific error message to try to guide them the right way.
	    // For example: https://github.com/Polymer/polymer-bundler/pull/519
	    if (aOriginal && typeof aOriginal.line !== 'number' && typeof aOriginal.column !== 'number') {
	      var message = 'original.line and original.column are not numbers -- you probably meant to omit ' +
	      'the original mapping entirely and only map the generated position. If so, pass ' +
	      'null for the original mapping instead of an object with empty or null values.';

	      if (this._ignoreInvalidMapping) {
	        if (typeof console !== 'undefined' && console.warn) {
	          console.warn(message);
	        }
	        return false;
	      } else {
	        throw new Error(message);
	      }
	    }

	    if (aGenerated && 'line' in aGenerated && 'column' in aGenerated
	        && aGenerated.line > 0 && aGenerated.column >= 0
	        && !aOriginal && !aSource && !aName) {
	      // Case 1.
	      return;
	    }
	    else if (aGenerated && 'line' in aGenerated && 'column' in aGenerated
	             && aOriginal && 'line' in aOriginal && 'column' in aOriginal
	             && aGenerated.line > 0 && aGenerated.column >= 0
	             && aOriginal.line > 0 && aOriginal.column >= 0
	             && aSource) {
	      // Cases 2 and 3.
	      return;
	    }
	    else {
	      var message = 'Invalid mapping: ' + JSON.stringify({
	        generated: aGenerated,
	        source: aSource,
	        original: aOriginal,
	        name: aName
	      });

	      if (this._ignoreInvalidMapping) {
	        if (typeof console !== 'undefined' && console.warn) {
	          console.warn(message);
	        }
	        return false;
	      } else {
	        throw new Error(message)
	      }
	    }
	  };

	/**
	 * Serialize the accumulated mappings in to the stream of base 64 VLQs
	 * specified by the source map format.
	 */
	SourceMapGenerator.prototype._serializeMappings =
	  function SourceMapGenerator_serializeMappings() {
	    var previousGeneratedColumn = 0;
	    var previousGeneratedLine = 1;
	    var previousOriginalColumn = 0;
	    var previousOriginalLine = 0;
	    var previousName = 0;
	    var previousSource = 0;
	    var result = '';
	    var next;
	    var mapping;
	    var nameIdx;
	    var sourceIdx;

	    var mappings = this._mappings.toArray();
	    for (var i = 0, len = mappings.length; i < len; i++) {
	      mapping = mappings[i];
	      next = '';

	      if (mapping.generatedLine !== previousGeneratedLine) {
	        previousGeneratedColumn = 0;
	        while (mapping.generatedLine !== previousGeneratedLine) {
	          next += ';';
	          previousGeneratedLine++;
	        }
	      }
	      else {
	        if (i > 0) {
	          if (!util.compareByGeneratedPositionsInflated(mapping, mappings[i - 1])) {
	            continue;
	          }
	          next += ',';
	        }
	      }

	      next += base64VLQ.encode(mapping.generatedColumn
	                                 - previousGeneratedColumn);
	      previousGeneratedColumn = mapping.generatedColumn;

	      if (mapping.source != null) {
	        sourceIdx = this._sources.indexOf(mapping.source);
	        next += base64VLQ.encode(sourceIdx - previousSource);
	        previousSource = sourceIdx;

	        // lines are stored 0-based in SourceMap spec version 3
	        next += base64VLQ.encode(mapping.originalLine - 1
	                                   - previousOriginalLine);
	        previousOriginalLine = mapping.originalLine - 1;

	        next += base64VLQ.encode(mapping.originalColumn
	                                   - previousOriginalColumn);
	        previousOriginalColumn = mapping.originalColumn;

	        if (mapping.name != null) {
	          nameIdx = this._names.indexOf(mapping.name);
	          next += base64VLQ.encode(nameIdx - previousName);
	          previousName = nameIdx;
	        }
	      }

	      result += next;
	    }

	    return result;
	  };

	SourceMapGenerator.prototype._generateSourcesContent =
	  function SourceMapGenerator_generateSourcesContent(aSources, aSourceRoot) {
	    return aSources.map(function (source) {
	      if (!this._sourcesContents) {
	        return null;
	      }
	      if (aSourceRoot != null) {
	        source = util.relative(aSourceRoot, source);
	      }
	      var key = util.toSetString(source);
	      return Object.prototype.hasOwnProperty.call(this._sourcesContents, key)
	        ? this._sourcesContents[key]
	        : null;
	    }, this);
	  };

	/**
	 * Externalize the source map.
	 */
	SourceMapGenerator.prototype.toJSON =
	  function SourceMapGenerator_toJSON() {
	    var map = {
	      version: this._version,
	      sources: this._sources.toArray(),
	      names: this._names.toArray(),
	      mappings: this._serializeMappings()
	    };
	    if (this._file != null) {
	      map.file = this._file;
	    }
	    if (this._sourceRoot != null) {
	      map.sourceRoot = this._sourceRoot;
	    }
	    if (this._sourcesContents) {
	      map.sourcesContent = this._generateSourcesContent(map.sources, map.sourceRoot);
	    }

	    return map;
	  };

	/**
	 * Render the source map being generated to a string.
	 */
	SourceMapGenerator.prototype.toString =
	  function SourceMapGenerator_toString() {
	    return JSON.stringify(this.toJSON());
	  };

	sourceMapGenerator.SourceMapGenerator = SourceMapGenerator;
	return sourceMapGenerator;
}

var sourceMapConsumer = {};

var binarySearch = {};

/* -*- Mode: js; js-indent-level: 2; -*- */

var hasRequiredBinarySearch;

function requireBinarySearch () {
	if (hasRequiredBinarySearch) return binarySearch;
	hasRequiredBinarySearch = 1;
	(function (exports) {
		/*
		 * Copyright 2011 Mozilla Foundation and contributors
		 * Licensed under the New BSD license. See LICENSE or:
		 * http://opensource.org/licenses/BSD-3-Clause
		 */

		exports.GREATEST_LOWER_BOUND = 1;
		exports.LEAST_UPPER_BOUND = 2;

		/**
		 * Recursive implementation of binary search.
		 *
		 * @param aLow Indices here and lower do not contain the needle.
		 * @param aHigh Indices here and higher do not contain the needle.
		 * @param aNeedle The element being searched for.
		 * @param aHaystack The non-empty array being searched.
		 * @param aCompare Function which takes two elements and returns -1, 0, or 1.
		 * @param aBias Either 'binarySearch.GREATEST_LOWER_BOUND' or
		 *     'binarySearch.LEAST_UPPER_BOUND'. Specifies whether to return the
		 *     closest element that is smaller than or greater than the one we are
		 *     searching for, respectively, if the exact element cannot be found.
		 */
		function recursiveSearch(aLow, aHigh, aNeedle, aHaystack, aCompare, aBias) {
		  // This function terminates when one of the following is true:
		  //
		  //   1. We find the exact element we are looking for.
		  //
		  //   2. We did not find the exact element, but we can return the index of
		  //      the next-closest element.
		  //
		  //   3. We did not find the exact element, and there is no next-closest
		  //      element than the one we are searching for, so we return -1.
		  var mid = Math.floor((aHigh - aLow) / 2) + aLow;
		  var cmp = aCompare(aNeedle, aHaystack[mid], true);
		  if (cmp === 0) {
		    // Found the element we are looking for.
		    return mid;
		  }
		  else if (cmp > 0) {
		    // Our needle is greater than aHaystack[mid].
		    if (aHigh - mid > 1) {
		      // The element is in the upper half.
		      return recursiveSearch(mid, aHigh, aNeedle, aHaystack, aCompare, aBias);
		    }

		    // The exact needle element was not found in this haystack. Determine if
		    // we are in termination case (3) or (2) and return the appropriate thing.
		    if (aBias == exports.LEAST_UPPER_BOUND) {
		      return aHigh < aHaystack.length ? aHigh : -1;
		    } else {
		      return mid;
		    }
		  }
		  else {
		    // Our needle is less than aHaystack[mid].
		    if (mid - aLow > 1) {
		      // The element is in the lower half.
		      return recursiveSearch(aLow, mid, aNeedle, aHaystack, aCompare, aBias);
		    }

		    // we are in termination case (3) or (2) and return the appropriate thing.
		    if (aBias == exports.LEAST_UPPER_BOUND) {
		      return mid;
		    } else {
		      return aLow < 0 ? -1 : aLow;
		    }
		  }
		}

		/**
		 * This is an implementation of binary search which will always try and return
		 * the index of the closest element if there is no exact hit. This is because
		 * mappings between original and generated line/col pairs are single points,
		 * and there is an implicit region between each of them, so a miss just means
		 * that you aren't on the very start of a region.
		 *
		 * @param aNeedle The element you are looking for.
		 * @param aHaystack The array that is being searched.
		 * @param aCompare A function which takes the needle and an element in the
		 *     array and returns -1, 0, or 1 depending on whether the needle is less
		 *     than, equal to, or greater than the element, respectively.
		 * @param aBias Either 'binarySearch.GREATEST_LOWER_BOUND' or
		 *     'binarySearch.LEAST_UPPER_BOUND'. Specifies whether to return the
		 *     closest element that is smaller than or greater than the one we are
		 *     searching for, respectively, if the exact element cannot be found.
		 *     Defaults to 'binarySearch.GREATEST_LOWER_BOUND'.
		 */
		exports.search = function search(aNeedle, aHaystack, aCompare, aBias) {
		  if (aHaystack.length === 0) {
		    return -1;
		  }

		  var index = recursiveSearch(-1, aHaystack.length, aNeedle, aHaystack,
		                              aCompare, aBias || exports.GREATEST_LOWER_BOUND);
		  if (index < 0) {
		    return -1;
		  }

		  // We have found either the exact element, or the next-closest element than
		  // the one we are searching for. However, there may be more than one such
		  // element. Make sure we always return the smallest of these.
		  while (index - 1 >= 0) {
		    if (aCompare(aHaystack[index], aHaystack[index - 1], true) !== 0) {
		      break;
		    }
		    --index;
		  }

		  return index;
		}; 
	} (binarySearch));
	return binarySearch;
}

var quickSort = {};

/* -*- Mode: js; js-indent-level: 2; -*- */

var hasRequiredQuickSort;

function requireQuickSort () {
	if (hasRequiredQuickSort) return quickSort;
	hasRequiredQuickSort = 1;
	/*
	 * Copyright 2011 Mozilla Foundation and contributors
	 * Licensed under the New BSD license. See LICENSE or:
	 * http://opensource.org/licenses/BSD-3-Clause
	 */

	// It turns out that some (most?) JavaScript engines don't self-host
	// `Array.prototype.sort`. This makes sense because C++ will likely remain
	// faster than JS when doing raw CPU-intensive sorting. However, when using a
	// custom comparator function, calling back and forth between the VM's C++ and
	// JIT'd JS is rather slow *and* loses JIT type information, resulting in
	// worse generated code for the comparator function than would be optimal. In
	// fact, when sorting with a comparator, these costs outweigh the benefits of
	// sorting in C++. By using our own JS-implemented Quick Sort (below), we get
	// a ~3500ms mean speed-up in `bench/bench.html`.

	function SortTemplate(comparator) {

	/**
	 * Swap the elements indexed by `x` and `y` in the array `ary`.
	 *
	 * @param {Array} ary
	 *        The array.
	 * @param {Number} x
	 *        The index of the first item.
	 * @param {Number} y
	 *        The index of the second item.
	 */
	function swap(ary, x, y) {
	  var temp = ary[x];
	  ary[x] = ary[y];
	  ary[y] = temp;
	}

	/**
	 * Returns a random integer within the range `low .. high` inclusive.
	 *
	 * @param {Number} low
	 *        The lower bound on the range.
	 * @param {Number} high
	 *        The upper bound on the range.
	 */
	function randomIntInRange(low, high) {
	  return Math.round(low + (Math.random() * (high - low)));
	}

	/**
	 * The Quick Sort algorithm.
	 *
	 * @param {Array} ary
	 *        An array to sort.
	 * @param {function} comparator
	 *        Function to use to compare two items.
	 * @param {Number} p
	 *        Start index of the array
	 * @param {Number} r
	 *        End index of the array
	 */
	function doQuickSort(ary, comparator, p, r) {
	  // If our lower bound is less than our upper bound, we (1) partition the
	  // array into two pieces and (2) recurse on each half. If it is not, this is
	  // the empty array and our base case.

	  if (p < r) {
	    // (1) Partitioning.
	    //
	    // The partitioning chooses a pivot between `p` and `r` and moves all
	    // elements that are less than or equal to the pivot to the before it, and
	    // all the elements that are greater than it after it. The effect is that
	    // once partition is done, the pivot is in the exact place it will be when
	    // the array is put in sorted order, and it will not need to be moved
	    // again. This runs in O(n) time.

	    // Always choose a random pivot so that an input array which is reverse
	    // sorted does not cause O(n^2) running time.
	    var pivotIndex = randomIntInRange(p, r);
	    var i = p - 1;

	    swap(ary, pivotIndex, r);
	    var pivot = ary[r];

	    // Immediately after `j` is incremented in this loop, the following hold
	    // true:
	    //
	    //   * Every element in `ary[p .. i]` is less than or equal to the pivot.
	    //
	    //   * Every element in `ary[i+1 .. j-1]` is greater than the pivot.
	    for (var j = p; j < r; j++) {
	      if (comparator(ary[j], pivot, false) <= 0) {
	        i += 1;
	        swap(ary, i, j);
	      }
	    }

	    swap(ary, i + 1, j);
	    var q = i + 1;

	    // (2) Recurse on each half.

	    doQuickSort(ary, comparator, p, q - 1);
	    doQuickSort(ary, comparator, q + 1, r);
	  }
	}

	  return doQuickSort;
	}

	function cloneSort(comparator) {
	  let template = SortTemplate.toString();
	  let templateFn = new Function(`return ${template}`)();
	  return templateFn(comparator);
	}

	/**
	 * Sort the given array in-place with the given comparator function.
	 *
	 * @param {Array} ary
	 *        An array to sort.
	 * @param {function} comparator
	 *        Function to use to compare two items.
	 */

	let sortCache = new WeakMap();
	quickSort.quickSort = function (ary, comparator, start = 0) {
	  let doQuickSort = sortCache.get(comparator);
	  if (doQuickSort === void 0) {
	    doQuickSort = cloneSort(comparator);
	    sortCache.set(comparator, doQuickSort);
	  }
	  doQuickSort(ary, comparator, start, ary.length - 1);
	};
	return quickSort;
}

/* -*- Mode: js; js-indent-level: 2; -*- */

var hasRequiredSourceMapConsumer;

function requireSourceMapConsumer () {
	if (hasRequiredSourceMapConsumer) return sourceMapConsumer;
	hasRequiredSourceMapConsumer = 1;
	/*
	 * Copyright 2011 Mozilla Foundation and contributors
	 * Licensed under the New BSD license. See LICENSE or:
	 * http://opensource.org/licenses/BSD-3-Clause
	 */

	var util = requireUtil();
	var binarySearch = requireBinarySearch();
	var ArraySet = requireArraySet().ArraySet;
	var base64VLQ = requireBase64Vlq();
	var quickSort = requireQuickSort().quickSort;

	function SourceMapConsumer(aSourceMap, aSourceMapURL) {
	  var sourceMap = aSourceMap;
	  if (typeof aSourceMap === 'string') {
	    sourceMap = util.parseSourceMapInput(aSourceMap);
	  }

	  return sourceMap.sections != null
	    ? new IndexedSourceMapConsumer(sourceMap, aSourceMapURL)
	    : new BasicSourceMapConsumer(sourceMap, aSourceMapURL);
	}

	SourceMapConsumer.fromSourceMap = function(aSourceMap, aSourceMapURL) {
	  return BasicSourceMapConsumer.fromSourceMap(aSourceMap, aSourceMapURL);
	};

	/**
	 * The version of the source mapping spec that we are consuming.
	 */
	SourceMapConsumer.prototype._version = 3;

	// `__generatedMappings` and `__originalMappings` are arrays that hold the
	// parsed mapping coordinates from the source map's "mappings" attribute. They
	// are lazily instantiated, accessed via the `_generatedMappings` and
	// `_originalMappings` getters respectively, and we only parse the mappings
	// and create these arrays once queried for a source location. We jump through
	// these hoops because there can be many thousands of mappings, and parsing
	// them is expensive, so we only want to do it if we must.
	//
	// Each object in the arrays is of the form:
	//
	//     {
	//       generatedLine: The line number in the generated code,
	//       generatedColumn: The column number in the generated code,
	//       source: The path to the original source file that generated this
	//               chunk of code,
	//       originalLine: The line number in the original source that
	//                     corresponds to this chunk of generated code,
	//       originalColumn: The column number in the original source that
	//                       corresponds to this chunk of generated code,
	//       name: The name of the original symbol which generated this chunk of
	//             code.
	//     }
	//
	// All properties except for `generatedLine` and `generatedColumn` can be
	// `null`.
	//
	// `_generatedMappings` is ordered by the generated positions.
	//
	// `_originalMappings` is ordered by the original positions.

	SourceMapConsumer.prototype.__generatedMappings = null;
	Object.defineProperty(SourceMapConsumer.prototype, '_generatedMappings', {
	  configurable: true,
	  enumerable: true,
	  get: function () {
	    if (!this.__generatedMappings) {
	      this._parseMappings(this._mappings, this.sourceRoot);
	    }

	    return this.__generatedMappings;
	  }
	});

	SourceMapConsumer.prototype.__originalMappings = null;
	Object.defineProperty(SourceMapConsumer.prototype, '_originalMappings', {
	  configurable: true,
	  enumerable: true,
	  get: function () {
	    if (!this.__originalMappings) {
	      this._parseMappings(this._mappings, this.sourceRoot);
	    }

	    return this.__originalMappings;
	  }
	});

	SourceMapConsumer.prototype._charIsMappingSeparator =
	  function SourceMapConsumer_charIsMappingSeparator(aStr, index) {
	    var c = aStr.charAt(index);
	    return c === ";" || c === ",";
	  };

	/**
	 * Parse the mappings in a string in to a data structure which we can easily
	 * query (the ordered arrays in the `this.__generatedMappings` and
	 * `this.__originalMappings` properties).
	 */
	SourceMapConsumer.prototype._parseMappings =
	  function SourceMapConsumer_parseMappings(aStr, aSourceRoot) {
	    throw new Error("Subclasses must implement _parseMappings");
	  };

	SourceMapConsumer.GENERATED_ORDER = 1;
	SourceMapConsumer.ORIGINAL_ORDER = 2;

	SourceMapConsumer.GREATEST_LOWER_BOUND = 1;
	SourceMapConsumer.LEAST_UPPER_BOUND = 2;

	/**
	 * Iterate over each mapping between an original source/line/column and a
	 * generated line/column in this source map.
	 *
	 * @param Function aCallback
	 *        The function that is called with each mapping.
	 * @param Object aContext
	 *        Optional. If specified, this object will be the value of `this` every
	 *        time that `aCallback` is called.
	 * @param aOrder
	 *        Either `SourceMapConsumer.GENERATED_ORDER` or
	 *        `SourceMapConsumer.ORIGINAL_ORDER`. Specifies whether you want to
	 *        iterate over the mappings sorted by the generated file's line/column
	 *        order or the original's source/line/column order, respectively. Defaults to
	 *        `SourceMapConsumer.GENERATED_ORDER`.
	 */
	SourceMapConsumer.prototype.eachMapping =
	  function SourceMapConsumer_eachMapping(aCallback, aContext, aOrder) {
	    var context = aContext || null;
	    var order = aOrder || SourceMapConsumer.GENERATED_ORDER;

	    var mappings;
	    switch (order) {
	    case SourceMapConsumer.GENERATED_ORDER:
	      mappings = this._generatedMappings;
	      break;
	    case SourceMapConsumer.ORIGINAL_ORDER:
	      mappings = this._originalMappings;
	      break;
	    default:
	      throw new Error("Unknown order of iteration.");
	    }

	    var sourceRoot = this.sourceRoot;
	    var boundCallback = aCallback.bind(context);
	    var names = this._names;
	    var sources = this._sources;
	    var sourceMapURL = this._sourceMapURL;

	    for (var i = 0, n = mappings.length; i < n; i++) {
	      var mapping = mappings[i];
	      var source = mapping.source === null ? null : sources.at(mapping.source);
	      if(source !== null) {
	        source = util.computeSourceURL(sourceRoot, source, sourceMapURL);
	      }
	      boundCallback({
	        source: source,
	        generatedLine: mapping.generatedLine,
	        generatedColumn: mapping.generatedColumn,
	        originalLine: mapping.originalLine,
	        originalColumn: mapping.originalColumn,
	        name: mapping.name === null ? null : names.at(mapping.name)
	      });
	    }
	  };

	/**
	 * Returns all generated line and column information for the original source,
	 * line, and column provided. If no column is provided, returns all mappings
	 * corresponding to a either the line we are searching for or the next
	 * closest line that has any mappings. Otherwise, returns all mappings
	 * corresponding to the given line and either the column we are searching for
	 * or the next closest column that has any offsets.
	 *
	 * The only argument is an object with the following properties:
	 *
	 *   - source: The filename of the original source.
	 *   - line: The line number in the original source.  The line number is 1-based.
	 *   - column: Optional. the column number in the original source.
	 *    The column number is 0-based.
	 *
	 * and an array of objects is returned, each with the following properties:
	 *
	 *   - line: The line number in the generated source, or null.  The
	 *    line number is 1-based.
	 *   - column: The column number in the generated source, or null.
	 *    The column number is 0-based.
	 */
	SourceMapConsumer.prototype.allGeneratedPositionsFor =
	  function SourceMapConsumer_allGeneratedPositionsFor(aArgs) {
	    var line = util.getArg(aArgs, 'line');

	    // When there is no exact match, BasicSourceMapConsumer.prototype._findMapping
	    // returns the index of the closest mapping less than the needle. By
	    // setting needle.originalColumn to 0, we thus find the last mapping for
	    // the given line, provided such a mapping exists.
	    var needle = {
	      source: util.getArg(aArgs, 'source'),
	      originalLine: line,
	      originalColumn: util.getArg(aArgs, 'column', 0)
	    };

	    needle.source = this._findSourceIndex(needle.source);
	    if (needle.source < 0) {
	      return [];
	    }

	    var mappings = [];

	    var index = this._findMapping(needle,
	                                  this._originalMappings,
	                                  "originalLine",
	                                  "originalColumn",
	                                  util.compareByOriginalPositions,
	                                  binarySearch.LEAST_UPPER_BOUND);
	    if (index >= 0) {
	      var mapping = this._originalMappings[index];

	      if (aArgs.column === undefined) {
	        var originalLine = mapping.originalLine;

	        // Iterate until either we run out of mappings, or we run into
	        // a mapping for a different line than the one we found. Since
	        // mappings are sorted, this is guaranteed to find all mappings for
	        // the line we found.
	        while (mapping && mapping.originalLine === originalLine) {
	          mappings.push({
	            line: util.getArg(mapping, 'generatedLine', null),
	            column: util.getArg(mapping, 'generatedColumn', null),
	            lastColumn: util.getArg(mapping, 'lastGeneratedColumn', null)
	          });

	          mapping = this._originalMappings[++index];
	        }
	      } else {
	        var originalColumn = mapping.originalColumn;

	        // Iterate until either we run out of mappings, or we run into
	        // a mapping for a different line than the one we were searching for.
	        // Since mappings are sorted, this is guaranteed to find all mappings for
	        // the line we are searching for.
	        while (mapping &&
	               mapping.originalLine === line &&
	               mapping.originalColumn == originalColumn) {
	          mappings.push({
	            line: util.getArg(mapping, 'generatedLine', null),
	            column: util.getArg(mapping, 'generatedColumn', null),
	            lastColumn: util.getArg(mapping, 'lastGeneratedColumn', null)
	          });

	          mapping = this._originalMappings[++index];
	        }
	      }
	    }

	    return mappings;
	  };

	sourceMapConsumer.SourceMapConsumer = SourceMapConsumer;

	/**
	 * A BasicSourceMapConsumer instance represents a parsed source map which we can
	 * query for information about the original file positions by giving it a file
	 * position in the generated source.
	 *
	 * The first parameter is the raw source map (either as a JSON string, or
	 * already parsed to an object). According to the spec, source maps have the
	 * following attributes:
	 *
	 *   - version: Which version of the source map spec this map is following.
	 *   - sources: An array of URLs to the original source files.
	 *   - names: An array of identifiers which can be referrenced by individual mappings.
	 *   - sourceRoot: Optional. The URL root from which all sources are relative.
	 *   - sourcesContent: Optional. An array of contents of the original source files.
	 *   - mappings: A string of base64 VLQs which contain the actual mappings.
	 *   - file: Optional. The generated file this source map is associated with.
	 *
	 * Here is an example source map, taken from the source map spec[0]:
	 *
	 *     {
	 *       version : 3,
	 *       file: "out.js",
	 *       sourceRoot : "",
	 *       sources: ["foo.js", "bar.js"],
	 *       names: ["src", "maps", "are", "fun"],
	 *       mappings: "AA,AB;;ABCDE;"
	 *     }
	 *
	 * The second parameter, if given, is a string whose value is the URL
	 * at which the source map was found.  This URL is used to compute the
	 * sources array.
	 *
	 * [0]: https://docs.google.com/document/d/1U1RGAehQwRypUTovF1KRlpiOFze0b-_2gc6fAH0KY0k/edit?pli=1#
	 */
	function BasicSourceMapConsumer(aSourceMap, aSourceMapURL) {
	  var sourceMap = aSourceMap;
	  if (typeof aSourceMap === 'string') {
	    sourceMap = util.parseSourceMapInput(aSourceMap);
	  }

	  var version = util.getArg(sourceMap, 'version');
	  var sources = util.getArg(sourceMap, 'sources');
	  // Sass 3.3 leaves out the 'names' array, so we deviate from the spec (which
	  // requires the array) to play nice here.
	  var names = util.getArg(sourceMap, 'names', []);
	  var sourceRoot = util.getArg(sourceMap, 'sourceRoot', null);
	  var sourcesContent = util.getArg(sourceMap, 'sourcesContent', null);
	  var mappings = util.getArg(sourceMap, 'mappings');
	  var file = util.getArg(sourceMap, 'file', null);

	  // Once again, Sass deviates from the spec and supplies the version as a
	  // string rather than a number, so we use loose equality checking here.
	  if (version != this._version) {
	    throw new Error('Unsupported version: ' + version);
	  }

	  if (sourceRoot) {
	    sourceRoot = util.normalize(sourceRoot);
	  }

	  sources = sources
	    .map(String)
	    // Some source maps produce relative source paths like "./foo.js" instead of
	    // "foo.js".  Normalize these first so that future comparisons will succeed.
	    // See bugzil.la/1090768.
	    .map(util.normalize)
	    // Always ensure that absolute sources are internally stored relative to
	    // the source root, if the source root is absolute. Not doing this would
	    // be particularly problematic when the source root is a prefix of the
	    // source (valid, but why??). See github issue #199 and bugzil.la/1188982.
	    .map(function (source) {
	      return sourceRoot && util.isAbsolute(sourceRoot) && util.isAbsolute(source)
	        ? util.relative(sourceRoot, source)
	        : source;
	    });

	  // Pass `true` below to allow duplicate names and sources. While source maps
	  // are intended to be compressed and deduplicated, the TypeScript compiler
	  // sometimes generates source maps with duplicates in them. See Github issue
	  // #72 and bugzil.la/889492.
	  this._names = ArraySet.fromArray(names.map(String), true);
	  this._sources = ArraySet.fromArray(sources, true);

	  this._absoluteSources = this._sources.toArray().map(function (s) {
	    return util.computeSourceURL(sourceRoot, s, aSourceMapURL);
	  });

	  this.sourceRoot = sourceRoot;
	  this.sourcesContent = sourcesContent;
	  this._mappings = mappings;
	  this._sourceMapURL = aSourceMapURL;
	  this.file = file;
	}

	BasicSourceMapConsumer.prototype = Object.create(SourceMapConsumer.prototype);
	BasicSourceMapConsumer.prototype.consumer = SourceMapConsumer;

	/**
	 * Utility function to find the index of a source.  Returns -1 if not
	 * found.
	 */
	BasicSourceMapConsumer.prototype._findSourceIndex = function(aSource) {
	  var relativeSource = aSource;
	  if (this.sourceRoot != null) {
	    relativeSource = util.relative(this.sourceRoot, relativeSource);
	  }

	  if (this._sources.has(relativeSource)) {
	    return this._sources.indexOf(relativeSource);
	  }

	  // Maybe aSource is an absolute URL as returned by |sources|.  In
	  // this case we can't simply undo the transform.
	  var i;
	  for (i = 0; i < this._absoluteSources.length; ++i) {
	    if (this._absoluteSources[i] == aSource) {
	      return i;
	    }
	  }

	  return -1;
	};

	/**
	 * Create a BasicSourceMapConsumer from a SourceMapGenerator.
	 *
	 * @param SourceMapGenerator aSourceMap
	 *        The source map that will be consumed.
	 * @param String aSourceMapURL
	 *        The URL at which the source map can be found (optional)
	 * @returns BasicSourceMapConsumer
	 */
	BasicSourceMapConsumer.fromSourceMap =
	  function SourceMapConsumer_fromSourceMap(aSourceMap, aSourceMapURL) {
	    var smc = Object.create(BasicSourceMapConsumer.prototype);

	    var names = smc._names = ArraySet.fromArray(aSourceMap._names.toArray(), true);
	    var sources = smc._sources = ArraySet.fromArray(aSourceMap._sources.toArray(), true);
	    smc.sourceRoot = aSourceMap._sourceRoot;
	    smc.sourcesContent = aSourceMap._generateSourcesContent(smc._sources.toArray(),
	                                                            smc.sourceRoot);
	    smc.file = aSourceMap._file;
	    smc._sourceMapURL = aSourceMapURL;
	    smc._absoluteSources = smc._sources.toArray().map(function (s) {
	      return util.computeSourceURL(smc.sourceRoot, s, aSourceMapURL);
	    });

	    // Because we are modifying the entries (by converting string sources and
	    // names to indices into the sources and names ArraySets), we have to make
	    // a copy of the entry or else bad things happen. Shared mutable state
	    // strikes again! See github issue #191.

	    var generatedMappings = aSourceMap._mappings.toArray().slice();
	    var destGeneratedMappings = smc.__generatedMappings = [];
	    var destOriginalMappings = smc.__originalMappings = [];

	    for (var i = 0, length = generatedMappings.length; i < length; i++) {
	      var srcMapping = generatedMappings[i];
	      var destMapping = new Mapping;
	      destMapping.generatedLine = srcMapping.generatedLine;
	      destMapping.generatedColumn = srcMapping.generatedColumn;

	      if (srcMapping.source) {
	        destMapping.source = sources.indexOf(srcMapping.source);
	        destMapping.originalLine = srcMapping.originalLine;
	        destMapping.originalColumn = srcMapping.originalColumn;

	        if (srcMapping.name) {
	          destMapping.name = names.indexOf(srcMapping.name);
	        }

	        destOriginalMappings.push(destMapping);
	      }

	      destGeneratedMappings.push(destMapping);
	    }

	    quickSort(smc.__originalMappings, util.compareByOriginalPositions);

	    return smc;
	  };

	/**
	 * The version of the source mapping spec that we are consuming.
	 */
	BasicSourceMapConsumer.prototype._version = 3;

	/**
	 * The list of original sources.
	 */
	Object.defineProperty(BasicSourceMapConsumer.prototype, 'sources', {
	  get: function () {
	    return this._absoluteSources.slice();
	  }
	});

	/**
	 * Provide the JIT with a nice shape / hidden class.
	 */
	function Mapping() {
	  this.generatedLine = 0;
	  this.generatedColumn = 0;
	  this.source = null;
	  this.originalLine = null;
	  this.originalColumn = null;
	  this.name = null;
	}

	/**
	 * Parse the mappings in a string in to a data structure which we can easily
	 * query (the ordered arrays in the `this.__generatedMappings` and
	 * `this.__originalMappings` properties).
	 */

	const compareGenerated = util.compareByGeneratedPositionsDeflatedNoLine;
	function sortGenerated(array, start) {
	  let l = array.length;
	  let n = array.length - start;
	  if (n <= 1) {
	    return;
	  } else if (n == 2) {
	    let a = array[start];
	    let b = array[start + 1];
	    if (compareGenerated(a, b) > 0) {
	      array[start] = b;
	      array[start + 1] = a;
	    }
	  } else if (n < 20) {
	    for (let i = start; i < l; i++) {
	      for (let j = i; j > start; j--) {
	        let a = array[j - 1];
	        let b = array[j];
	        if (compareGenerated(a, b) <= 0) {
	          break;
	        }
	        array[j - 1] = b;
	        array[j] = a;
	      }
	    }
	  } else {
	    quickSort(array, compareGenerated, start);
	  }
	}
	BasicSourceMapConsumer.prototype._parseMappings =
	  function SourceMapConsumer_parseMappings(aStr, aSourceRoot) {
	    var generatedLine = 1;
	    var previousGeneratedColumn = 0;
	    var previousOriginalLine = 0;
	    var previousOriginalColumn = 0;
	    var previousSource = 0;
	    var previousName = 0;
	    var length = aStr.length;
	    var index = 0;
	    var temp = {};
	    var originalMappings = [];
	    var generatedMappings = [];
	    var mapping, segment, end, value;

	    let subarrayStart = 0;
	    while (index < length) {
	      if (aStr.charAt(index) === ';') {
	        generatedLine++;
	        index++;
	        previousGeneratedColumn = 0;

	        sortGenerated(generatedMappings, subarrayStart);
	        subarrayStart = generatedMappings.length;
	      }
	      else if (aStr.charAt(index) === ',') {
	        index++;
	      }
	      else {
	        mapping = new Mapping();
	        mapping.generatedLine = generatedLine;

	        for (end = index; end < length; end++) {
	          if (this._charIsMappingSeparator(aStr, end)) {
	            break;
	          }
	        }
	        aStr.slice(index, end);

	        segment = [];
	        while (index < end) {
	          base64VLQ.decode(aStr, index, temp);
	          value = temp.value;
	          index = temp.rest;
	          segment.push(value);
	        }

	        if (segment.length === 2) {
	          throw new Error('Found a source, but no line and column');
	        }

	        if (segment.length === 3) {
	          throw new Error('Found a source and line, but no column');
	        }

	        // Generated column.
	        mapping.generatedColumn = previousGeneratedColumn + segment[0];
	        previousGeneratedColumn = mapping.generatedColumn;

	        if (segment.length > 1) {
	          // Original source.
	          mapping.source = previousSource + segment[1];
	          previousSource += segment[1];

	          // Original line.
	          mapping.originalLine = previousOriginalLine + segment[2];
	          previousOriginalLine = mapping.originalLine;
	          // Lines are stored 0-based
	          mapping.originalLine += 1;

	          // Original column.
	          mapping.originalColumn = previousOriginalColumn + segment[3];
	          previousOriginalColumn = mapping.originalColumn;

	          if (segment.length > 4) {
	            // Original name.
	            mapping.name = previousName + segment[4];
	            previousName += segment[4];
	          }
	        }

	        generatedMappings.push(mapping);
	        if (typeof mapping.originalLine === 'number') {
	          let currentSource = mapping.source;
	          while (originalMappings.length <= currentSource) {
	            originalMappings.push(null);
	          }
	          if (originalMappings[currentSource] === null) {
	            originalMappings[currentSource] = [];
	          }
	          originalMappings[currentSource].push(mapping);
	        }
	      }
	    }

	    sortGenerated(generatedMappings, subarrayStart);
	    this.__generatedMappings = generatedMappings;

	    for (var i = 0; i < originalMappings.length; i++) {
	      if (originalMappings[i] != null) {
	        quickSort(originalMappings[i], util.compareByOriginalPositionsNoSource);
	      }
	    }
	    this.__originalMappings = [].concat(...originalMappings);
	  };

	/**
	 * Find the mapping that best matches the hypothetical "needle" mapping that
	 * we are searching for in the given "haystack" of mappings.
	 */
	BasicSourceMapConsumer.prototype._findMapping =
	  function SourceMapConsumer_findMapping(aNeedle, aMappings, aLineName,
	                                         aColumnName, aComparator, aBias) {
	    // To return the position we are searching for, we must first find the
	    // mapping for the given position and then return the opposite position it
	    // points to. Because the mappings are sorted, we can use binary search to
	    // find the best mapping.

	    if (aNeedle[aLineName] <= 0) {
	      throw new TypeError('Line must be greater than or equal to 1, got '
	                          + aNeedle[aLineName]);
	    }
	    if (aNeedle[aColumnName] < 0) {
	      throw new TypeError('Column must be greater than or equal to 0, got '
	                          + aNeedle[aColumnName]);
	    }

	    return binarySearch.search(aNeedle, aMappings, aComparator, aBias);
	  };

	/**
	 * Compute the last column for each generated mapping. The last column is
	 * inclusive.
	 */
	BasicSourceMapConsumer.prototype.computeColumnSpans =
	  function SourceMapConsumer_computeColumnSpans() {
	    for (var index = 0; index < this._generatedMappings.length; ++index) {
	      var mapping = this._generatedMappings[index];

	      // Mappings do not contain a field for the last generated columnt. We
	      // can come up with an optimistic estimate, however, by assuming that
	      // mappings are contiguous (i.e. given two consecutive mappings, the
	      // first mapping ends where the second one starts).
	      if (index + 1 < this._generatedMappings.length) {
	        var nextMapping = this._generatedMappings[index + 1];

	        if (mapping.generatedLine === nextMapping.generatedLine) {
	          mapping.lastGeneratedColumn = nextMapping.generatedColumn - 1;
	          continue;
	        }
	      }

	      // The last mapping for each line spans the entire line.
	      mapping.lastGeneratedColumn = Infinity;
	    }
	  };

	/**
	 * Returns the original source, line, and column information for the generated
	 * source's line and column positions provided. The only argument is an object
	 * with the following properties:
	 *
	 *   - line: The line number in the generated source.  The line number
	 *     is 1-based.
	 *   - column: The column number in the generated source.  The column
	 *     number is 0-based.
	 *   - bias: Either 'SourceMapConsumer.GREATEST_LOWER_BOUND' or
	 *     'SourceMapConsumer.LEAST_UPPER_BOUND'. Specifies whether to return the
	 *     closest element that is smaller than or greater than the one we are
	 *     searching for, respectively, if the exact element cannot be found.
	 *     Defaults to 'SourceMapConsumer.GREATEST_LOWER_BOUND'.
	 *
	 * and an object is returned with the following properties:
	 *
	 *   - source: The original source file, or null.
	 *   - line: The line number in the original source, or null.  The
	 *     line number is 1-based.
	 *   - column: The column number in the original source, or null.  The
	 *     column number is 0-based.
	 *   - name: The original identifier, or null.
	 */
	BasicSourceMapConsumer.prototype.originalPositionFor =
	  function SourceMapConsumer_originalPositionFor(aArgs) {
	    var needle = {
	      generatedLine: util.getArg(aArgs, 'line'),
	      generatedColumn: util.getArg(aArgs, 'column')
	    };

	    var index = this._findMapping(
	      needle,
	      this._generatedMappings,
	      "generatedLine",
	      "generatedColumn",
	      util.compareByGeneratedPositionsDeflated,
	      util.getArg(aArgs, 'bias', SourceMapConsumer.GREATEST_LOWER_BOUND)
	    );

	    if (index >= 0) {
	      var mapping = this._generatedMappings[index];

	      if (mapping.generatedLine === needle.generatedLine) {
	        var source = util.getArg(mapping, 'source', null);
	        if (source !== null) {
	          source = this._sources.at(source);
	          source = util.computeSourceURL(this.sourceRoot, source, this._sourceMapURL);
	        }
	        var name = util.getArg(mapping, 'name', null);
	        if (name !== null) {
	          name = this._names.at(name);
	        }
	        return {
	          source: source,
	          line: util.getArg(mapping, 'originalLine', null),
	          column: util.getArg(mapping, 'originalColumn', null),
	          name: name
	        };
	      }
	    }

	    return {
	      source: null,
	      line: null,
	      column: null,
	      name: null
	    };
	  };

	/**
	 * Return true if we have the source content for every source in the source
	 * map, false otherwise.
	 */
	BasicSourceMapConsumer.prototype.hasContentsOfAllSources =
	  function BasicSourceMapConsumer_hasContentsOfAllSources() {
	    if (!this.sourcesContent) {
	      return false;
	    }
	    return this.sourcesContent.length >= this._sources.size() &&
	      !this.sourcesContent.some(function (sc) { return sc == null; });
	  };

	/**
	 * Returns the original source content. The only argument is the url of the
	 * original source file. Returns null if no original source content is
	 * available.
	 */
	BasicSourceMapConsumer.prototype.sourceContentFor =
	  function SourceMapConsumer_sourceContentFor(aSource, nullOnMissing) {
	    if (!this.sourcesContent) {
	      return null;
	    }

	    var index = this._findSourceIndex(aSource);
	    if (index >= 0) {
	      return this.sourcesContent[index];
	    }

	    var relativeSource = aSource;
	    if (this.sourceRoot != null) {
	      relativeSource = util.relative(this.sourceRoot, relativeSource);
	    }

	    var url;
	    if (this.sourceRoot != null
	        && (url = util.urlParse(this.sourceRoot))) {
	      // XXX: file:// URIs and absolute paths lead to unexpected behavior for
	      // many users. We can help them out when they expect file:// URIs to
	      // behave like it would if they were running a local HTTP server. See
	      // https://bugzilla.mozilla.org/show_bug.cgi?id=885597.
	      var fileUriAbsPath = relativeSource.replace(/^file:\/\//, "");
	      if (url.scheme == "file"
	          && this._sources.has(fileUriAbsPath)) {
	        return this.sourcesContent[this._sources.indexOf(fileUriAbsPath)]
	      }

	      if ((!url.path || url.path == "/")
	          && this._sources.has("/" + relativeSource)) {
	        return this.sourcesContent[this._sources.indexOf("/" + relativeSource)];
	      }
	    }

	    // This function is used recursively from
	    // IndexedSourceMapConsumer.prototype.sourceContentFor. In that case, we
	    // don't want to throw if we can't find the source - we just want to
	    // return null, so we provide a flag to exit gracefully.
	    if (nullOnMissing) {
	      return null;
	    }
	    else {
	      throw new Error('"' + relativeSource + '" is not in the SourceMap.');
	    }
	  };

	/**
	 * Returns the generated line and column information for the original source,
	 * line, and column positions provided. The only argument is an object with
	 * the following properties:
	 *
	 *   - source: The filename of the original source.
	 *   - line: The line number in the original source.  The line number
	 *     is 1-based.
	 *   - column: The column number in the original source.  The column
	 *     number is 0-based.
	 *   - bias: Either 'SourceMapConsumer.GREATEST_LOWER_BOUND' or
	 *     'SourceMapConsumer.LEAST_UPPER_BOUND'. Specifies whether to return the
	 *     closest element that is smaller than or greater than the one we are
	 *     searching for, respectively, if the exact element cannot be found.
	 *     Defaults to 'SourceMapConsumer.GREATEST_LOWER_BOUND'.
	 *
	 * and an object is returned with the following properties:
	 *
	 *   - line: The line number in the generated source, or null.  The
	 *     line number is 1-based.
	 *   - column: The column number in the generated source, or null.
	 *     The column number is 0-based.
	 */
	BasicSourceMapConsumer.prototype.generatedPositionFor =
	  function SourceMapConsumer_generatedPositionFor(aArgs) {
	    var source = util.getArg(aArgs, 'source');
	    source = this._findSourceIndex(source);
	    if (source < 0) {
	      return {
	        line: null,
	        column: null,
	        lastColumn: null
	      };
	    }

	    var needle = {
	      source: source,
	      originalLine: util.getArg(aArgs, 'line'),
	      originalColumn: util.getArg(aArgs, 'column')
	    };

	    var index = this._findMapping(
	      needle,
	      this._originalMappings,
	      "originalLine",
	      "originalColumn",
	      util.compareByOriginalPositions,
	      util.getArg(aArgs, 'bias', SourceMapConsumer.GREATEST_LOWER_BOUND)
	    );

	    if (index >= 0) {
	      var mapping = this._originalMappings[index];

	      if (mapping.source === needle.source) {
	        return {
	          line: util.getArg(mapping, 'generatedLine', null),
	          column: util.getArg(mapping, 'generatedColumn', null),
	          lastColumn: util.getArg(mapping, 'lastGeneratedColumn', null)
	        };
	      }
	    }

	    return {
	      line: null,
	      column: null,
	      lastColumn: null
	    };
	  };

	sourceMapConsumer.BasicSourceMapConsumer = BasicSourceMapConsumer;

	/**
	 * An IndexedSourceMapConsumer instance represents a parsed source map which
	 * we can query for information. It differs from BasicSourceMapConsumer in
	 * that it takes "indexed" source maps (i.e. ones with a "sections" field) as
	 * input.
	 *
	 * The first parameter is a raw source map (either as a JSON string, or already
	 * parsed to an object). According to the spec for indexed source maps, they
	 * have the following attributes:
	 *
	 *   - version: Which version of the source map spec this map is following.
	 *   - file: Optional. The generated file this source map is associated with.
	 *   - sections: A list of section definitions.
	 *
	 * Each value under the "sections" field has two fields:
	 *   - offset: The offset into the original specified at which this section
	 *       begins to apply, defined as an object with a "line" and "column"
	 *       field.
	 *   - map: A source map definition. This source map could also be indexed,
	 *       but doesn't have to be.
	 *
	 * Instead of the "map" field, it's also possible to have a "url" field
	 * specifying a URL to retrieve a source map from, but that's currently
	 * unsupported.
	 *
	 * Here's an example source map, taken from the source map spec[0], but
	 * modified to omit a section which uses the "url" field.
	 *
	 *  {
	 *    version : 3,
	 *    file: "app.js",
	 *    sections: [{
	 *      offset: {line:100, column:10},
	 *      map: {
	 *        version : 3,
	 *        file: "section.js",
	 *        sources: ["foo.js", "bar.js"],
	 *        names: ["src", "maps", "are", "fun"],
	 *        mappings: "AAAA,E;;ABCDE;"
	 *      }
	 *    }],
	 *  }
	 *
	 * The second parameter, if given, is a string whose value is the URL
	 * at which the source map was found.  This URL is used to compute the
	 * sources array.
	 *
	 * [0]: https://docs.google.com/document/d/1U1RGAehQwRypUTovF1KRlpiOFze0b-_2gc6fAH0KY0k/edit#heading=h.535es3xeprgt
	 */
	function IndexedSourceMapConsumer(aSourceMap, aSourceMapURL) {
	  var sourceMap = aSourceMap;
	  if (typeof aSourceMap === 'string') {
	    sourceMap = util.parseSourceMapInput(aSourceMap);
	  }

	  var version = util.getArg(sourceMap, 'version');
	  var sections = util.getArg(sourceMap, 'sections');

	  if (version != this._version) {
	    throw new Error('Unsupported version: ' + version);
	  }

	  this._sources = new ArraySet();
	  this._names = new ArraySet();

	  var lastOffset = {
	    line: -1,
	    column: 0
	  };
	  this._sections = sections.map(function (s) {
	    if (s.url) {
	      // The url field will require support for asynchronicity.
	      // See https://github.com/mozilla/source-map/issues/16
	      throw new Error('Support for url field in sections not implemented.');
	    }
	    var offset = util.getArg(s, 'offset');
	    var offsetLine = util.getArg(offset, 'line');
	    var offsetColumn = util.getArg(offset, 'column');

	    if (offsetLine < lastOffset.line ||
	        (offsetLine === lastOffset.line && offsetColumn < lastOffset.column)) {
	      throw new Error('Section offsets must be ordered and non-overlapping.');
	    }
	    lastOffset = offset;

	    return {
	      generatedOffset: {
	        // The offset fields are 0-based, but we use 1-based indices when
	        // encoding/decoding from VLQ.
	        generatedLine: offsetLine + 1,
	        generatedColumn: offsetColumn + 1
	      },
	      consumer: new SourceMapConsumer(util.getArg(s, 'map'), aSourceMapURL)
	    }
	  });
	}

	IndexedSourceMapConsumer.prototype = Object.create(SourceMapConsumer.prototype);
	IndexedSourceMapConsumer.prototype.constructor = SourceMapConsumer;

	/**
	 * The version of the source mapping spec that we are consuming.
	 */
	IndexedSourceMapConsumer.prototype._version = 3;

	/**
	 * The list of original sources.
	 */
	Object.defineProperty(IndexedSourceMapConsumer.prototype, 'sources', {
	  get: function () {
	    var sources = [];
	    for (var i = 0; i < this._sections.length; i++) {
	      for (var j = 0; j < this._sections[i].consumer.sources.length; j++) {
	        sources.push(this._sections[i].consumer.sources[j]);
	      }
	    }
	    return sources;
	  }
	});

	/**
	 * Returns the original source, line, and column information for the generated
	 * source's line and column positions provided. The only argument is an object
	 * with the following properties:
	 *
	 *   - line: The line number in the generated source.  The line number
	 *     is 1-based.
	 *   - column: The column number in the generated source.  The column
	 *     number is 0-based.
	 *
	 * and an object is returned with the following properties:
	 *
	 *   - source: The original source file, or null.
	 *   - line: The line number in the original source, or null.  The
	 *     line number is 1-based.
	 *   - column: The column number in the original source, or null.  The
	 *     column number is 0-based.
	 *   - name: The original identifier, or null.
	 */
	IndexedSourceMapConsumer.prototype.originalPositionFor =
	  function IndexedSourceMapConsumer_originalPositionFor(aArgs) {
	    var needle = {
	      generatedLine: util.getArg(aArgs, 'line'),
	      generatedColumn: util.getArg(aArgs, 'column')
	    };

	    // Find the section containing the generated position we're trying to map
	    // to an original position.
	    var sectionIndex = binarySearch.search(needle, this._sections,
	      function(needle, section) {
	        var cmp = needle.generatedLine - section.generatedOffset.generatedLine;
	        if (cmp) {
	          return cmp;
	        }

	        return (needle.generatedColumn -
	                section.generatedOffset.generatedColumn);
	      });
	    var section = this._sections[sectionIndex];

	    if (!section) {
	      return {
	        source: null,
	        line: null,
	        column: null,
	        name: null
	      };
	    }

	    return section.consumer.originalPositionFor({
	      line: needle.generatedLine -
	        (section.generatedOffset.generatedLine - 1),
	      column: needle.generatedColumn -
	        (section.generatedOffset.generatedLine === needle.generatedLine
	         ? section.generatedOffset.generatedColumn - 1
	         : 0),
	      bias: aArgs.bias
	    });
	  };

	/**
	 * Return true if we have the source content for every source in the source
	 * map, false otherwise.
	 */
	IndexedSourceMapConsumer.prototype.hasContentsOfAllSources =
	  function IndexedSourceMapConsumer_hasContentsOfAllSources() {
	    return this._sections.every(function (s) {
	      return s.consumer.hasContentsOfAllSources();
	    });
	  };

	/**
	 * Returns the original source content. The only argument is the url of the
	 * original source file. Returns null if no original source content is
	 * available.
	 */
	IndexedSourceMapConsumer.prototype.sourceContentFor =
	  function IndexedSourceMapConsumer_sourceContentFor(aSource, nullOnMissing) {
	    for (var i = 0; i < this._sections.length; i++) {
	      var section = this._sections[i];

	      var content = section.consumer.sourceContentFor(aSource, true);
	      if (content || content === '') {
	        return content;
	      }
	    }
	    if (nullOnMissing) {
	      return null;
	    }
	    else {
	      throw new Error('"' + aSource + '" is not in the SourceMap.');
	    }
	  };

	/**
	 * Returns the generated line and column information for the original source,
	 * line, and column positions provided. The only argument is an object with
	 * the following properties:
	 *
	 *   - source: The filename of the original source.
	 *   - line: The line number in the original source.  The line number
	 *     is 1-based.
	 *   - column: The column number in the original source.  The column
	 *     number is 0-based.
	 *
	 * and an object is returned with the following properties:
	 *
	 *   - line: The line number in the generated source, or null.  The
	 *     line number is 1-based. 
	 *   - column: The column number in the generated source, or null.
	 *     The column number is 0-based.
	 */
	IndexedSourceMapConsumer.prototype.generatedPositionFor =
	  function IndexedSourceMapConsumer_generatedPositionFor(aArgs) {
	    for (var i = 0; i < this._sections.length; i++) {
	      var section = this._sections[i];

	      // Only consider this section if the requested source is in the list of
	      // sources of the consumer.
	      if (section.consumer._findSourceIndex(util.getArg(aArgs, 'source')) === -1) {
	        continue;
	      }
	      var generatedPosition = section.consumer.generatedPositionFor(aArgs);
	      if (generatedPosition) {
	        var ret = {
	          line: generatedPosition.line +
	            (section.generatedOffset.generatedLine - 1),
	          column: generatedPosition.column +
	            (section.generatedOffset.generatedLine === generatedPosition.line
	             ? section.generatedOffset.generatedColumn - 1
	             : 0)
	        };
	        return ret;
	      }
	    }

	    return {
	      line: null,
	      column: null
	    };
	  };

	/**
	 * Parse the mappings in a string in to a data structure which we can easily
	 * query (the ordered arrays in the `this.__generatedMappings` and
	 * `this.__originalMappings` properties).
	 */
	IndexedSourceMapConsumer.prototype._parseMappings =
	  function IndexedSourceMapConsumer_parseMappings(aStr, aSourceRoot) {
	    this.__generatedMappings = [];
	    this.__originalMappings = [];
	    for (var i = 0; i < this._sections.length; i++) {
	      var section = this._sections[i];
	      var sectionMappings = section.consumer._generatedMappings;
	      for (var j = 0; j < sectionMappings.length; j++) {
	        var mapping = sectionMappings[j];

	        var source = section.consumer._sources.at(mapping.source);
	        if(source !== null) {
	          source = util.computeSourceURL(section.consumer.sourceRoot, source, this._sourceMapURL);
	        }
	        this._sources.add(source);
	        source = this._sources.indexOf(source);

	        var name = null;
	        if (mapping.name) {
	          name = section.consumer._names.at(mapping.name);
	          this._names.add(name);
	          name = this._names.indexOf(name);
	        }

	        // The mappings coming from the consumer for the section have
	        // generated positions relative to the start of the section, so we
	        // need to offset them to be relative to the start of the concatenated
	        // generated file.
	        var adjustedMapping = {
	          source: source,
	          generatedLine: mapping.generatedLine +
	            (section.generatedOffset.generatedLine - 1),
	          generatedColumn: mapping.generatedColumn +
	            (section.generatedOffset.generatedLine === mapping.generatedLine
	            ? section.generatedOffset.generatedColumn - 1
	            : 0),
	          originalLine: mapping.originalLine,
	          originalColumn: mapping.originalColumn,
	          name: name
	        };

	        this.__generatedMappings.push(adjustedMapping);
	        if (typeof adjustedMapping.originalLine === 'number') {
	          this.__originalMappings.push(adjustedMapping);
	        }
	      }
	    }

	    quickSort(this.__generatedMappings, util.compareByGeneratedPositionsDeflated);
	    quickSort(this.__originalMappings, util.compareByOriginalPositions);
	  };

	sourceMapConsumer.IndexedSourceMapConsumer = IndexedSourceMapConsumer;
	return sourceMapConsumer;
}

var sourceNode = {};

/* -*- Mode: js; js-indent-level: 2; -*- */

var hasRequiredSourceNode;

function requireSourceNode () {
	if (hasRequiredSourceNode) return sourceNode;
	hasRequiredSourceNode = 1;
	/*
	 * Copyright 2011 Mozilla Foundation and contributors
	 * Licensed under the New BSD license. See LICENSE or:
	 * http://opensource.org/licenses/BSD-3-Clause
	 */

	var SourceMapGenerator = requireSourceMapGenerator().SourceMapGenerator;
	var util = requireUtil();

	// Matches a Windows-style `\r\n` newline or a `\n` newline used by all other
	// operating systems these days (capturing the result).
	var REGEX_NEWLINE = /(\r?\n)/;

	// Newline character code for charCodeAt() comparisons
	var NEWLINE_CODE = 10;

	// Private symbol for identifying `SourceNode`s when multiple versions of
	// the source-map library are loaded. This MUST NOT CHANGE across
	// versions!
	var isSourceNode = "$$$isSourceNode$$$";

	/**
	 * SourceNodes provide a way to abstract over interpolating/concatenating
	 * snippets of generated JavaScript source code while maintaining the line and
	 * column information associated with the original source code.
	 *
	 * @param aLine The original line number.
	 * @param aColumn The original column number.
	 * @param aSource The original source's filename.
	 * @param aChunks Optional. An array of strings which are snippets of
	 *        generated JS, or other SourceNodes.
	 * @param aName The original identifier.
	 */
	function SourceNode(aLine, aColumn, aSource, aChunks, aName) {
	  this.children = [];
	  this.sourceContents = {};
	  this.line = aLine == null ? null : aLine;
	  this.column = aColumn == null ? null : aColumn;
	  this.source = aSource == null ? null : aSource;
	  this.name = aName == null ? null : aName;
	  this[isSourceNode] = true;
	  if (aChunks != null) this.add(aChunks);
	}

	/**
	 * Creates a SourceNode from generated code and a SourceMapConsumer.
	 *
	 * @param aGeneratedCode The generated code
	 * @param aSourceMapConsumer The SourceMap for the generated code
	 * @param aRelativePath Optional. The path that relative sources in the
	 *        SourceMapConsumer should be relative to.
	 */
	SourceNode.fromStringWithSourceMap =
	  function SourceNode_fromStringWithSourceMap(aGeneratedCode, aSourceMapConsumer, aRelativePath) {
	    // The SourceNode we want to fill with the generated code
	    // and the SourceMap
	    var node = new SourceNode();

	    // All even indices of this array are one line of the generated code,
	    // while all odd indices are the newlines between two adjacent lines
	    // (since `REGEX_NEWLINE` captures its match).
	    // Processed fragments are accessed by calling `shiftNextLine`.
	    var remainingLines = aGeneratedCode.split(REGEX_NEWLINE);
	    var remainingLinesIndex = 0;
	    var shiftNextLine = function() {
	      var lineContents = getNextLine();
	      // The last line of a file might not have a newline.
	      var newLine = getNextLine() || "";
	      return lineContents + newLine;

	      function getNextLine() {
	        return remainingLinesIndex < remainingLines.length ?
	            remainingLines[remainingLinesIndex++] : undefined;
	      }
	    };

	    // We need to remember the position of "remainingLines"
	    var lastGeneratedLine = 1, lastGeneratedColumn = 0;

	    // The generate SourceNodes we need a code range.
	    // To extract it current and last mapping is used.
	    // Here we store the last mapping.
	    var lastMapping = null;

	    aSourceMapConsumer.eachMapping(function (mapping) {
	      if (lastMapping !== null) {
	        // We add the code from "lastMapping" to "mapping":
	        // First check if there is a new line in between.
	        if (lastGeneratedLine < mapping.generatedLine) {
	          // Associate first line with "lastMapping"
	          addMappingWithCode(lastMapping, shiftNextLine());
	          lastGeneratedLine++;
	          lastGeneratedColumn = 0;
	          // The remaining code is added without mapping
	        } else {
	          // There is no new line in between.
	          // Associate the code between "lastGeneratedColumn" and
	          // "mapping.generatedColumn" with "lastMapping"
	          var nextLine = remainingLines[remainingLinesIndex] || '';
	          var code = nextLine.substr(0, mapping.generatedColumn -
	                                        lastGeneratedColumn);
	          remainingLines[remainingLinesIndex] = nextLine.substr(mapping.generatedColumn -
	                                              lastGeneratedColumn);
	          lastGeneratedColumn = mapping.generatedColumn;
	          addMappingWithCode(lastMapping, code);
	          // No more remaining code, continue
	          lastMapping = mapping;
	          return;
	        }
	      }
	      // We add the generated code until the first mapping
	      // to the SourceNode without any mapping.
	      // Each line is added as separate string.
	      while (lastGeneratedLine < mapping.generatedLine) {
	        node.add(shiftNextLine());
	        lastGeneratedLine++;
	      }
	      if (lastGeneratedColumn < mapping.generatedColumn) {
	        var nextLine = remainingLines[remainingLinesIndex] || '';
	        node.add(nextLine.substr(0, mapping.generatedColumn));
	        remainingLines[remainingLinesIndex] = nextLine.substr(mapping.generatedColumn);
	        lastGeneratedColumn = mapping.generatedColumn;
	      }
	      lastMapping = mapping;
	    }, this);
	    // We have processed all mappings.
	    if (remainingLinesIndex < remainingLines.length) {
	      if (lastMapping) {
	        // Associate the remaining code in the current line with "lastMapping"
	        addMappingWithCode(lastMapping, shiftNextLine());
	      }
	      // and add the remaining lines without any mapping
	      node.add(remainingLines.splice(remainingLinesIndex).join(""));
	    }

	    // Copy sourcesContent into SourceNode
	    aSourceMapConsumer.sources.forEach(function (sourceFile) {
	      var content = aSourceMapConsumer.sourceContentFor(sourceFile);
	      if (content != null) {
	        if (aRelativePath != null) {
	          sourceFile = util.join(aRelativePath, sourceFile);
	        }
	        node.setSourceContent(sourceFile, content);
	      }
	    });

	    return node;

	    function addMappingWithCode(mapping, code) {
	      if (mapping === null || mapping.source === undefined) {
	        node.add(code);
	      } else {
	        var source = aRelativePath
	          ? util.join(aRelativePath, mapping.source)
	          : mapping.source;
	        node.add(new SourceNode(mapping.originalLine,
	                                mapping.originalColumn,
	                                source,
	                                code,
	                                mapping.name));
	      }
	    }
	  };

	/**
	 * Add a chunk of generated JS to this source node.
	 *
	 * @param aChunk A string snippet of generated JS code, another instance of
	 *        SourceNode, or an array where each member is one of those things.
	 */
	SourceNode.prototype.add = function SourceNode_add(aChunk) {
	  if (Array.isArray(aChunk)) {
	    aChunk.forEach(function (chunk) {
	      this.add(chunk);
	    }, this);
	  }
	  else if (aChunk[isSourceNode] || typeof aChunk === "string") {
	    if (aChunk) {
	      this.children.push(aChunk);
	    }
	  }
	  else {
	    throw new TypeError(
	      "Expected a SourceNode, string, or an array of SourceNodes and strings. Got " + aChunk
	    );
	  }
	  return this;
	};

	/**
	 * Add a chunk of generated JS to the beginning of this source node.
	 *
	 * @param aChunk A string snippet of generated JS code, another instance of
	 *        SourceNode, or an array where each member is one of those things.
	 */
	SourceNode.prototype.prepend = function SourceNode_prepend(aChunk) {
	  if (Array.isArray(aChunk)) {
	    for (var i = aChunk.length-1; i >= 0; i--) {
	      this.prepend(aChunk[i]);
	    }
	  }
	  else if (aChunk[isSourceNode] || typeof aChunk === "string") {
	    this.children.unshift(aChunk);
	  }
	  else {
	    throw new TypeError(
	      "Expected a SourceNode, string, or an array of SourceNodes and strings. Got " + aChunk
	    );
	  }
	  return this;
	};

	/**
	 * Walk over the tree of JS snippets in this node and its children. The
	 * walking function is called once for each snippet of JS and is passed that
	 * snippet and the its original associated source's line/column location.
	 *
	 * @param aFn The traversal function.
	 */
	SourceNode.prototype.walk = function SourceNode_walk(aFn) {
	  var chunk;
	  for (var i = 0, len = this.children.length; i < len; i++) {
	    chunk = this.children[i];
	    if (chunk[isSourceNode]) {
	      chunk.walk(aFn);
	    }
	    else {
	      if (chunk !== '') {
	        aFn(chunk, { source: this.source,
	                     line: this.line,
	                     column: this.column,
	                     name: this.name });
	      }
	    }
	  }
	};

	/**
	 * Like `String.prototype.join` except for SourceNodes. Inserts `aStr` between
	 * each of `this.children`.
	 *
	 * @param aSep The separator.
	 */
	SourceNode.prototype.join = function SourceNode_join(aSep) {
	  var newChildren;
	  var i;
	  var len = this.children.length;
	  if (len > 0) {
	    newChildren = [];
	    for (i = 0; i < len-1; i++) {
	      newChildren.push(this.children[i]);
	      newChildren.push(aSep);
	    }
	    newChildren.push(this.children[i]);
	    this.children = newChildren;
	  }
	  return this;
	};

	/**
	 * Call String.prototype.replace on the very right-most source snippet. Useful
	 * for trimming whitespace from the end of a source node, etc.
	 *
	 * @param aPattern The pattern to replace.
	 * @param aReplacement The thing to replace the pattern with.
	 */
	SourceNode.prototype.replaceRight = function SourceNode_replaceRight(aPattern, aReplacement) {
	  var lastChild = this.children[this.children.length - 1];
	  if (lastChild[isSourceNode]) {
	    lastChild.replaceRight(aPattern, aReplacement);
	  }
	  else if (typeof lastChild === 'string') {
	    this.children[this.children.length - 1] = lastChild.replace(aPattern, aReplacement);
	  }
	  else {
	    this.children.push(''.replace(aPattern, aReplacement));
	  }
	  return this;
	};

	/**
	 * Set the source content for a source file. This will be added to the SourceMapGenerator
	 * in the sourcesContent field.
	 *
	 * @param aSourceFile The filename of the source file
	 * @param aSourceContent The content of the source file
	 */
	SourceNode.prototype.setSourceContent =
	  function SourceNode_setSourceContent(aSourceFile, aSourceContent) {
	    this.sourceContents[util.toSetString(aSourceFile)] = aSourceContent;
	  };

	/**
	 * Walk over the tree of SourceNodes. The walking function is called for each
	 * source file content and is passed the filename and source content.
	 *
	 * @param aFn The traversal function.
	 */
	SourceNode.prototype.walkSourceContents =
	  function SourceNode_walkSourceContents(aFn) {
	    for (var i = 0, len = this.children.length; i < len; i++) {
	      if (this.children[i][isSourceNode]) {
	        this.children[i].walkSourceContents(aFn);
	      }
	    }

	    var sources = Object.keys(this.sourceContents);
	    for (var i = 0, len = sources.length; i < len; i++) {
	      aFn(util.fromSetString(sources[i]), this.sourceContents[sources[i]]);
	    }
	  };

	/**
	 * Return the string representation of this source node. Walks over the tree
	 * and concatenates all the various snippets together to one string.
	 */
	SourceNode.prototype.toString = function SourceNode_toString() {
	  var str = "";
	  this.walk(function (chunk) {
	    str += chunk;
	  });
	  return str;
	};

	/**
	 * Returns the string representation of this source node along with a source
	 * map.
	 */
	SourceNode.prototype.toStringWithSourceMap = function SourceNode_toStringWithSourceMap(aArgs) {
	  var generated = {
	    code: "",
	    line: 1,
	    column: 0
	  };
	  var map = new SourceMapGenerator(aArgs);
	  var sourceMappingActive = false;
	  var lastOriginalSource = null;
	  var lastOriginalLine = null;
	  var lastOriginalColumn = null;
	  var lastOriginalName = null;
	  this.walk(function (chunk, original) {
	    generated.code += chunk;
	    if (original.source !== null
	        && original.line !== null
	        && original.column !== null) {
	      if(lastOriginalSource !== original.source
	         || lastOriginalLine !== original.line
	         || lastOriginalColumn !== original.column
	         || lastOriginalName !== original.name) {
	        map.addMapping({
	          source: original.source,
	          original: {
	            line: original.line,
	            column: original.column
	          },
	          generated: {
	            line: generated.line,
	            column: generated.column
	          },
	          name: original.name
	        });
	      }
	      lastOriginalSource = original.source;
	      lastOriginalLine = original.line;
	      lastOriginalColumn = original.column;
	      lastOriginalName = original.name;
	      sourceMappingActive = true;
	    } else if (sourceMappingActive) {
	      map.addMapping({
	        generated: {
	          line: generated.line,
	          column: generated.column
	        }
	      });
	      lastOriginalSource = null;
	      sourceMappingActive = false;
	    }
	    for (var idx = 0, length = chunk.length; idx < length; idx++) {
	      if (chunk.charCodeAt(idx) === NEWLINE_CODE) {
	        generated.line++;
	        generated.column = 0;
	        // Mappings end at eol
	        if (idx + 1 === length) {
	          lastOriginalSource = null;
	          sourceMappingActive = false;
	        } else if (sourceMappingActive) {
	          map.addMapping({
	            source: original.source,
	            original: {
	              line: original.line,
	              column: original.column
	            },
	            generated: {
	              line: generated.line,
	              column: generated.column
	            },
	            name: original.name
	          });
	        }
	      } else {
	        generated.column++;
	      }
	    }
	  });
	  this.walkSourceContents(function (sourceFile, sourceContent) {
	    map.setSourceContent(sourceFile, sourceContent);
	  });

	  return { code: generated.code, map: map };
	};

	sourceNode.SourceNode = SourceNode;
	return sourceNode;
}

/*
 * Copyright 2009-2011 Mozilla Foundation and contributors
 * Licensed under the New BSD license. See LICENSE.txt or:
 * http://opensource.org/licenses/BSD-3-Clause
 */

var hasRequiredSourceMap;

function requireSourceMap () {
	if (hasRequiredSourceMap) return sourceMap;
	hasRequiredSourceMap = 1;
	sourceMap.SourceMapGenerator = requireSourceMapGenerator().SourceMapGenerator;
	sourceMap.SourceMapConsumer = requireSourceMapConsumer().SourceMapConsumer;
	sourceMap.SourceNode = requireSourceNode().SourceNode;
	return sourceMap;
}

var nonSecure;
var hasRequiredNonSecure;

function requireNonSecure () {
	if (hasRequiredNonSecure) return nonSecure;
	hasRequiredNonSecure = 1;
	// This alphabet uses `A-Za-z0-9_-` symbols.
	// The order of characters is optimized for better gzip and brotli compression.
	// References to the same file (works both for gzip and brotli):
	// `'use`, `andom`, and `rict'`
	// References to the brotli default dictionary:
	// `-26T`, `1983`, `40px`, `75px`, `bush`, `jack`, `mind`, `very`, and `wolf`
	let urlAlphabet =
	  'useandom-26T198340PX75pxJACKVERYMINDBUSHWOLF_GQZbfghjklqvwyzrict';

	let customAlphabet = (alphabet, defaultSize = 21) => {
	  return (size = defaultSize) => {
	    let id = '';
	    // A compact alternative for `for (var i = 0; i < step; i++)`.
	    let i = size | 0;
	    while (i--) {
	      // `| 0` is more compact and faster than `Math.floor()`.
	      id += alphabet[(Math.random() * alphabet.length) | 0];
	    }
	    return id
	  }
	};

	let nanoid = (size = 21) => {
	  let id = '';
	  // A compact alternative for `for (var i = 0; i < step; i++)`.
	  let i = size | 0;
	  while (i--) {
	    // `| 0` is more compact and faster than `Math.floor()`.
	    id += urlAlphabet[(Math.random() * 64) | 0];
	  }
	  return id
	};

	nonSecure = { nanoid, customAlphabet };
	return nonSecure;
}

var previousMap;
var hasRequiredPreviousMap;

function requirePreviousMap () {
	if (hasRequiredPreviousMap) return previousMap;
	hasRequiredPreviousMap = 1;

	let { SourceMapConsumer, SourceMapGenerator } = requireSourceMap();
	let { existsSync, readFileSync } = require$$1;
	let { dirname, join } = require$$2;

	function fromBase64(str) {
	  if (Buffer) {
	    return Buffer.from(str, 'base64').toString()
	  } else {
	    /* c8 ignore next 2 */
	    return window.atob(str)
	  }
	}

	class PreviousMap {
	  constructor(css, opts) {
	    if (opts.map === false) return
	    this.loadAnnotation(css);
	    this.inline = this.startWith(this.annotation, 'data:');

	    let prev = opts.map ? opts.map.prev : undefined;
	    let text = this.loadMap(opts.from, prev);
	    if (!this.mapFile && opts.from) {
	      this.mapFile = opts.from;
	    }
	    if (this.mapFile) this.root = dirname(this.mapFile);
	    if (text) this.text = text;
	  }

	  consumer() {
	    if (!this.consumerCache) {
	      this.consumerCache = new SourceMapConsumer(this.text);
	    }
	    return this.consumerCache
	  }

	  decodeInline(text) {
	    let baseCharsetUri = /^data:application\/json;charset=utf-?8;base64,/;
	    let baseUri = /^data:application\/json;base64,/;
	    let charsetUri = /^data:application\/json;charset=utf-?8,/;
	    let uri = /^data:application\/json,/;

	    if (charsetUri.test(text) || uri.test(text)) {
	      return decodeURIComponent(text.substr(RegExp.lastMatch.length))
	    }

	    if (baseCharsetUri.test(text) || baseUri.test(text)) {
	      return fromBase64(text.substr(RegExp.lastMatch.length))
	    }

	    let encoding = text.match(/data:application\/json;([^,]+),/)[1];
	    throw new Error('Unsupported source map encoding ' + encoding)
	  }

	  getAnnotationURL(sourceMapString) {
	    return sourceMapString.replace(/^\/\*\s*# sourceMappingURL=/, '').trim()
	  }

	  isMap(map) {
	    if (typeof map !== 'object') return false
	    return (
	      typeof map.mappings === 'string' ||
	      typeof map._mappings === 'string' ||
	      Array.isArray(map.sections)
	    )
	  }

	  loadAnnotation(css) {
	    let comments = css.match(/\/\*\s*# sourceMappingURL=/gm);
	    if (!comments) return

	    // sourceMappingURLs from comments, strings, etc.
	    let start = css.lastIndexOf(comments.pop());
	    let end = css.indexOf('*/', start);

	    if (start > -1 && end > -1) {
	      // Locate the last sourceMappingURL to avoid pickin
	      this.annotation = this.getAnnotationURL(css.substring(start, end));
	    }
	  }

	  loadFile(path) {
	    this.root = dirname(path);
	    if (existsSync(path)) {
	      this.mapFile = path;
	      return readFileSync(path, 'utf-8').toString().trim()
	    }
	  }

	  loadMap(file, prev) {
	    if (prev === false) return false

	    if (prev) {
	      if (typeof prev === 'string') {
	        return prev
	      } else if (typeof prev === 'function') {
	        let prevPath = prev(file);
	        if (prevPath) {
	          let map = this.loadFile(prevPath);
	          if (!map) {
	            throw new Error(
	              'Unable to load previous source map: ' + prevPath.toString()
	            )
	          }
	          return map
	        }
	      } else if (prev instanceof SourceMapConsumer) {
	        return SourceMapGenerator.fromSourceMap(prev).toString()
	      } else if (prev instanceof SourceMapGenerator) {
	        return prev.toString()
	      } else if (this.isMap(prev)) {
	        return JSON.stringify(prev)
	      } else {
	        throw new Error(
	          'Unsupported previous source map format: ' + prev.toString()
	        )
	      }
	    } else if (this.inline) {
	      return this.decodeInline(this.annotation)
	    } else if (this.annotation) {
	      let map = this.annotation;
	      if (file) map = join(dirname(file), map);
	      return this.loadFile(map)
	    }
	  }

	  startWith(string, start) {
	    if (!string) return false
	    return string.substr(0, start.length) === start
	  }

	  withContent() {
	    return !!(
	      this.consumer().sourcesContent &&
	      this.consumer().sourcesContent.length > 0
	    )
	  }
	}

	previousMap = PreviousMap;
	PreviousMap.default = PreviousMap;
	return previousMap;
}

var input;
var hasRequiredInput;

function requireInput () {
	if (hasRequiredInput) return input;
	hasRequiredInput = 1;

	let { SourceMapConsumer, SourceMapGenerator } = requireSourceMap();
	let { fileURLToPath, pathToFileURL } = require$$1$1;
	let { isAbsolute, resolve } = require$$2;
	let { nanoid } = requireNonSecure();

	let terminalHighlight = requireTerminalHighlight();
	let CssSyntaxError = requireCssSyntaxError();
	let PreviousMap = requirePreviousMap();

	let fromOffsetCache = Symbol('fromOffsetCache');

	let sourceMapAvailable = Boolean(SourceMapConsumer && SourceMapGenerator);
	let pathAvailable = Boolean(resolve && isAbsolute);

	class Input {
	  constructor(css, opts = {}) {
	    if (
	      css === null ||
	      typeof css === 'undefined' ||
	      (typeof css === 'object' && !css.toString)
	    ) {
	      throw new Error(`PostCSS received ${css} instead of CSS string`)
	    }

	    this.css = css.toString();

	    if (this.css[0] === '\uFEFF' || this.css[0] === '\uFFFE') {
	      this.hasBOM = true;
	      this.css = this.css.slice(1);
	    } else {
	      this.hasBOM = false;
	    }

	    if (opts.from) {
	      if (
	        !pathAvailable ||
	        /^\w+:\/\//.test(opts.from) ||
	        isAbsolute(opts.from)
	      ) {
	        this.file = opts.from;
	      } else {
	        this.file = resolve(opts.from);
	      }
	    }

	    if (pathAvailable && sourceMapAvailable) {
	      let map = new PreviousMap(this.css, opts);
	      if (map.text) {
	        this.map = map;
	        let file = map.consumer().file;
	        if (!this.file && file) this.file = this.mapResolve(file);
	      }
	    }

	    if (!this.file) {
	      this.id = '<input css ' + nanoid(6) + '>';
	    }
	    if (this.map) this.map.file = this.from;
	  }

	  error(message, line, column, opts = {}) {
	    let result, endLine, endColumn;

	    if (line && typeof line === 'object') {
	      let start = line;
	      let end = column;
	      if (typeof start.offset === 'number') {
	        let pos = this.fromOffset(start.offset);
	        line = pos.line;
	        column = pos.col;
	      } else {
	        line = start.line;
	        column = start.column;
	      }
	      if (typeof end.offset === 'number') {
	        let pos = this.fromOffset(end.offset);
	        endLine = pos.line;
	        endColumn = pos.col;
	      } else {
	        endLine = end.line;
	        endColumn = end.column;
	      }
	    } else if (!column) {
	      let pos = this.fromOffset(line);
	      line = pos.line;
	      column = pos.col;
	    }

	    let origin = this.origin(line, column, endLine, endColumn);
	    if (origin) {
	      result = new CssSyntaxError(
	        message,
	        origin.endLine === undefined
	          ? origin.line
	          : { column: origin.column, line: origin.line },
	        origin.endLine === undefined
	          ? origin.column
	          : { column: origin.endColumn, line: origin.endLine },
	        origin.source,
	        origin.file,
	        opts.plugin
	      );
	    } else {
	      result = new CssSyntaxError(
	        message,
	        endLine === undefined ? line : { column, line },
	        endLine === undefined ? column : { column: endColumn, line: endLine },
	        this.css,
	        this.file,
	        opts.plugin
	      );
	    }

	    result.input = { column, endColumn, endLine, line, source: this.css };
	    if (this.file) {
	      if (pathToFileURL) {
	        result.input.url = pathToFileURL(this.file).toString();
	      }
	      result.input.file = this.file;
	    }

	    return result
	  }

	  fromOffset(offset) {
	    let lastLine, lineToIndex;
	    if (!this[fromOffsetCache]) {
	      let lines = this.css.split('\n');
	      lineToIndex = new Array(lines.length);
	      let prevIndex = 0;

	      for (let i = 0, l = lines.length; i < l; i++) {
	        lineToIndex[i] = prevIndex;
	        prevIndex += lines[i].length + 1;
	      }

	      this[fromOffsetCache] = lineToIndex;
	    } else {
	      lineToIndex = this[fromOffsetCache];
	    }
	    lastLine = lineToIndex[lineToIndex.length - 1];

	    let min = 0;
	    if (offset >= lastLine) {
	      min = lineToIndex.length - 1;
	    } else {
	      let max = lineToIndex.length - 2;
	      let mid;
	      while (min < max) {
	        mid = min + ((max - min) >> 1);
	        if (offset < lineToIndex[mid]) {
	          max = mid - 1;
	        } else if (offset >= lineToIndex[mid + 1]) {
	          min = mid + 1;
	        } else {
	          min = mid;
	          break
	        }
	      }
	    }
	    return {
	      col: offset - lineToIndex[min] + 1,
	      line: min + 1
	    }
	  }

	  mapResolve(file) {
	    if (/^\w+:\/\//.test(file)) {
	      return file
	    }
	    return resolve(this.map.consumer().sourceRoot || this.map.root || '.', file)
	  }

	  origin(line, column, endLine, endColumn) {
	    if (!this.map) return false
	    let consumer = this.map.consumer();

	    let from = consumer.originalPositionFor({ column, line });
	    if (!from.source) return false

	    let to;
	    if (typeof endLine === 'number') {
	      to = consumer.originalPositionFor({ column: endColumn, line: endLine });
	    }

	    let fromUrl;

	    if (isAbsolute(from.source)) {
	      fromUrl = pathToFileURL(from.source);
	    } else {
	      fromUrl = new URL(
	        from.source,
	        this.map.consumer().sourceRoot || pathToFileURL(this.map.mapFile)
	      );
	    }

	    let result = {
	      column: from.column,
	      endColumn: to && to.column,
	      endLine: to && to.line,
	      line: from.line,
	      url: fromUrl.toString()
	    };

	    if (fromUrl.protocol === 'file:') {
	      if (fileURLToPath) {
	        result.file = fileURLToPath(fromUrl);
	      } else {
	        /* c8 ignore next 2 */
	        throw new Error(`file: protocol is not available in this PostCSS build`)
	      }
	    }

	    let source = consumer.sourceContentFor(from.source);
	    if (source) result.source = source;

	    return result
	  }

	  toJSON() {
	    let json = {};
	    for (let name of ['hasBOM', 'css', 'file', 'id']) {
	      if (this[name] != null) {
	        json[name] = this[name];
	      }
	    }
	    if (this.map) {
	      json.map = { ...this.map };
	      if (json.map.consumerCache) {
	        json.map.consumerCache = undefined;
	      }
	    }
	    return json
	  }

	  get from() {
	    return this.file || this.id
	  }
	}

	input = Input;
	Input.default = Input;

	if (terminalHighlight && terminalHighlight.registerInput) {
	  terminalHighlight.registerInput(Input);
	}
	return input;
}

var mapGenerator;
var hasRequiredMapGenerator;

function requireMapGenerator () {
	if (hasRequiredMapGenerator) return mapGenerator;
	hasRequiredMapGenerator = 1;

	let { SourceMapConsumer, SourceMapGenerator } = requireSourceMap();
	let { dirname, relative, resolve, sep } = require$$2;
	let { pathToFileURL } = require$$1$1;

	let Input = requireInput();

	let sourceMapAvailable = Boolean(SourceMapConsumer && SourceMapGenerator);
	let pathAvailable = Boolean(dirname && resolve && relative && sep);

	class MapGenerator {
	  constructor(stringify, root, opts, cssString) {
	    this.stringify = stringify;
	    this.mapOpts = opts.map || {};
	    this.root = root;
	    this.opts = opts;
	    this.css = cssString;
	    this.originalCSS = cssString;
	    this.usesFileUrls = !this.mapOpts.from && this.mapOpts.absolute;

	    this.memoizedFileURLs = new Map();
	    this.memoizedPaths = new Map();
	    this.memoizedURLs = new Map();
	  }

	  addAnnotation() {
	    let content;

	    if (this.isInline()) {
	      content =
	        'data:application/json;base64,' + this.toBase64(this.map.toString());
	    } else if (typeof this.mapOpts.annotation === 'string') {
	      content = this.mapOpts.annotation;
	    } else if (typeof this.mapOpts.annotation === 'function') {
	      content = this.mapOpts.annotation(this.opts.to, this.root);
	    } else {
	      content = this.outputFile() + '.map';
	    }
	    let eol = '\n';
	    if (this.css.includes('\r\n')) eol = '\r\n';

	    this.css += eol + '/*# sourceMappingURL=' + content + ' */';
	  }

	  applyPrevMaps() {
	    for (let prev of this.previous()) {
	      let from = this.toUrl(this.path(prev.file));
	      let root = prev.root || dirname(prev.file);
	      let map;

	      if (this.mapOpts.sourcesContent === false) {
	        map = new SourceMapConsumer(prev.text);
	        if (map.sourcesContent) {
	          map.sourcesContent = null;
	        }
	      } else {
	        map = prev.consumer();
	      }

	      this.map.applySourceMap(map, from, this.toUrl(this.path(root)));
	    }
	  }

	  clearAnnotation() {
	    if (this.mapOpts.annotation === false) return

	    if (this.root) {
	      let node;
	      for (let i = this.root.nodes.length - 1; i >= 0; i--) {
	        node = this.root.nodes[i];
	        if (node.type !== 'comment') continue
	        if (node.text.indexOf('# sourceMappingURL=') === 0) {
	          this.root.removeChild(i);
	        }
	      }
	    } else if (this.css) {
	      this.css = this.css.replace(/\n*?\/\*#[\S\s]*?\*\/$/gm, '');
	    }
	  }

	  generate() {
	    this.clearAnnotation();
	    if (pathAvailable && sourceMapAvailable && this.isMap()) {
	      return this.generateMap()
	    } else {
	      let result = '';
	      this.stringify(this.root, i => {
	        result += i;
	      });
	      return [result]
	    }
	  }

	  generateMap() {
	    if (this.root) {
	      this.generateString();
	    } else if (this.previous().length === 1) {
	      let prev = this.previous()[0].consumer();
	      prev.file = this.outputFile();
	      this.map = SourceMapGenerator.fromSourceMap(prev, {
	        ignoreInvalidMapping: true
	      });
	    } else {
	      this.map = new SourceMapGenerator({
	        file: this.outputFile(),
	        ignoreInvalidMapping: true
	      });
	      this.map.addMapping({
	        generated: { column: 0, line: 1 },
	        original: { column: 0, line: 1 },
	        source: this.opts.from
	          ? this.toUrl(this.path(this.opts.from))
	          : '<no source>'
	      });
	    }

	    if (this.isSourcesContent()) this.setSourcesContent();
	    if (this.root && this.previous().length > 0) this.applyPrevMaps();
	    if (this.isAnnotation()) this.addAnnotation();

	    if (this.isInline()) {
	      return [this.css]
	    } else {
	      return [this.css, this.map]
	    }
	  }

	  generateString() {
	    this.css = '';
	    this.map = new SourceMapGenerator({
	      file: this.outputFile(),
	      ignoreInvalidMapping: true
	    });

	    let line = 1;
	    let column = 1;

	    let noSource = '<no source>';
	    let mapping = {
	      generated: { column: 0, line: 0 },
	      original: { column: 0, line: 0 },
	      source: ''
	    };

	    let lines, last;
	    this.stringify(this.root, (str, node, type) => {
	      this.css += str;

	      if (node && type !== 'end') {
	        mapping.generated.line = line;
	        mapping.generated.column = column - 1;
	        if (node.source && node.source.start) {
	          mapping.source = this.sourcePath(node);
	          mapping.original.line = node.source.start.line;
	          mapping.original.column = node.source.start.column - 1;
	          this.map.addMapping(mapping);
	        } else {
	          mapping.source = noSource;
	          mapping.original.line = 1;
	          mapping.original.column = 0;
	          this.map.addMapping(mapping);
	        }
	      }

	      lines = str.match(/\n/g);
	      if (lines) {
	        line += lines.length;
	        last = str.lastIndexOf('\n');
	        column = str.length - last;
	      } else {
	        column += str.length;
	      }

	      if (node && type !== 'start') {
	        let p = node.parent || { raws: {} };
	        let childless =
	          node.type === 'decl' || (node.type === 'atrule' && !node.nodes);
	        if (!childless || node !== p.last || p.raws.semicolon) {
	          if (node.source && node.source.end) {
	            mapping.source = this.sourcePath(node);
	            mapping.original.line = node.source.end.line;
	            mapping.original.column = node.source.end.column - 1;
	            mapping.generated.line = line;
	            mapping.generated.column = column - 2;
	            this.map.addMapping(mapping);
	          } else {
	            mapping.source = noSource;
	            mapping.original.line = 1;
	            mapping.original.column = 0;
	            mapping.generated.line = line;
	            mapping.generated.column = column - 1;
	            this.map.addMapping(mapping);
	          }
	        }
	      }
	    });
	  }

	  isAnnotation() {
	    if (this.isInline()) {
	      return true
	    }
	    if (typeof this.mapOpts.annotation !== 'undefined') {
	      return this.mapOpts.annotation
	    }
	    if (this.previous().length) {
	      return this.previous().some(i => i.annotation)
	    }
	    return true
	  }

	  isInline() {
	    if (typeof this.mapOpts.inline !== 'undefined') {
	      return this.mapOpts.inline
	    }

	    let annotation = this.mapOpts.annotation;
	    if (typeof annotation !== 'undefined' && annotation !== true) {
	      return false
	    }

	    if (this.previous().length) {
	      return this.previous().some(i => i.inline)
	    }
	    return true
	  }

	  isMap() {
	    if (typeof this.opts.map !== 'undefined') {
	      return !!this.opts.map
	    }
	    return this.previous().length > 0
	  }

	  isSourcesContent() {
	    if (typeof this.mapOpts.sourcesContent !== 'undefined') {
	      return this.mapOpts.sourcesContent
	    }
	    if (this.previous().length) {
	      return this.previous().some(i => i.withContent())
	    }
	    return true
	  }

	  outputFile() {
	    if (this.opts.to) {
	      return this.path(this.opts.to)
	    } else if (this.opts.from) {
	      return this.path(this.opts.from)
	    } else {
	      return 'to.css'
	    }
	  }

	  path(file) {
	    if (this.mapOpts.absolute) return file
	    if (file.charCodeAt(0) === 60 /* `<` */) return file
	    if (/^\w+:\/\//.test(file)) return file
	    let cached = this.memoizedPaths.get(file);
	    if (cached) return cached

	    let from = this.opts.to ? dirname(this.opts.to) : '.';

	    if (typeof this.mapOpts.annotation === 'string') {
	      from = dirname(resolve(from, this.mapOpts.annotation));
	    }

	    let path = relative(from, file);
	    this.memoizedPaths.set(file, path);

	    return path
	  }

	  previous() {
	    if (!this.previousMaps) {
	      this.previousMaps = [];
	      if (this.root) {
	        this.root.walk(node => {
	          if (node.source && node.source.input.map) {
	            let map = node.source.input.map;
	            if (!this.previousMaps.includes(map)) {
	              this.previousMaps.push(map);
	            }
	          }
	        });
	      } else {
	        let input = new Input(this.originalCSS, this.opts);
	        if (input.map) this.previousMaps.push(input.map);
	      }
	    }

	    return this.previousMaps
	  }

	  setSourcesContent() {
	    let already = {};
	    if (this.root) {
	      this.root.walk(node => {
	        if (node.source) {
	          let from = node.source.input.from;
	          if (from && !already[from]) {
	            already[from] = true;
	            let fromUrl = this.usesFileUrls
	              ? this.toFileUrl(from)
	              : this.toUrl(this.path(from));
	            this.map.setSourceContent(fromUrl, node.source.input.css);
	          }
	        }
	      });
	    } else if (this.css) {
	      let from = this.opts.from
	        ? this.toUrl(this.path(this.opts.from))
	        : '<no source>';
	      this.map.setSourceContent(from, this.css);
	    }
	  }

	  sourcePath(node) {
	    if (this.mapOpts.from) {
	      return this.toUrl(this.mapOpts.from)
	    } else if (this.usesFileUrls) {
	      return this.toFileUrl(node.source.input.from)
	    } else {
	      return this.toUrl(this.path(node.source.input.from))
	    }
	  }

	  toBase64(str) {
	    if (Buffer) {
	      return Buffer.from(str).toString('base64')
	    } else {
	      return window.btoa(unescape(encodeURIComponent(str)))
	    }
	  }

	  toFileUrl(path) {
	    let cached = this.memoizedFileURLs.get(path);
	    if (cached) return cached

	    if (pathToFileURL) {
	      let fileURL = pathToFileURL(path).toString();
	      this.memoizedFileURLs.set(path, fileURL);

	      return fileURL
	    } else {
	      throw new Error(
	        '`map.absolute` option is not available in this PostCSS build'
	      )
	    }
	  }

	  toUrl(path) {
	    let cached = this.memoizedURLs.get(path);
	    if (cached) return cached

	    if (sep === '\\') {
	      path = path.replace(/\\/g, '/');
	    }

	    let url = encodeURI(path).replace(/[#?]/g, encodeURIComponent);
	    this.memoizedURLs.set(path, url);

	    return url
	  }
	}

	mapGenerator = MapGenerator;
	return mapGenerator;
}

var comment;
var hasRequiredComment;

function requireComment () {
	if (hasRequiredComment) return comment;
	hasRequiredComment = 1;

	let Node = requireNode();

	class Comment extends Node {
	  constructor(defaults) {
	    super(defaults);
	    this.type = 'comment';
	  }
	}

	comment = Comment;
	Comment.default = Comment;
	return comment;
}

var container;
var hasRequiredContainer;

function requireContainer () {
	if (hasRequiredContainer) return container;
	hasRequiredContainer = 1;

	let { isClean, my } = requireSymbols();
	let Declaration = requireDeclaration();
	let Comment = requireComment();
	let Node = requireNode();

	let parse, Rule, AtRule, Root;

	function cleanSource(nodes) {
	  return nodes.map(i => {
	    if (i.nodes) i.nodes = cleanSource(i.nodes);
	    delete i.source;
	    return i
	  })
	}

	function markDirtyUp(node) {
	  node[isClean] = false;
	  if (node.proxyOf.nodes) {
	    for (let i of node.proxyOf.nodes) {
	      markDirtyUp(i);
	    }
	  }
	}

	class Container extends Node {
	  append(...children) {
	    for (let child of children) {
	      let nodes = this.normalize(child, this.last);
	      for (let node of nodes) this.proxyOf.nodes.push(node);
	    }

	    this.markDirty();

	    return this
	  }

	  cleanRaws(keepBetween) {
	    super.cleanRaws(keepBetween);
	    if (this.nodes) {
	      for (let node of this.nodes) node.cleanRaws(keepBetween);
	    }
	  }

	  each(callback) {
	    if (!this.proxyOf.nodes) return undefined
	    let iterator = this.getIterator();

	    let index, result;
	    while (this.indexes[iterator] < this.proxyOf.nodes.length) {
	      index = this.indexes[iterator];
	      result = callback(this.proxyOf.nodes[index], index);
	      if (result === false) break

	      this.indexes[iterator] += 1;
	    }

	    delete this.indexes[iterator];
	    return result
	  }

	  every(condition) {
	    return this.nodes.every(condition)
	  }

	  getIterator() {
	    if (!this.lastEach) this.lastEach = 0;
	    if (!this.indexes) this.indexes = {};

	    this.lastEach += 1;
	    let iterator = this.lastEach;
	    this.indexes[iterator] = 0;

	    return iterator
	  }

	  getProxyProcessor() {
	    return {
	      get(node, prop) {
	        if (prop === 'proxyOf') {
	          return node
	        } else if (!node[prop]) {
	          return node[prop]
	        } else if (
	          prop === 'each' ||
	          (typeof prop === 'string' && prop.startsWith('walk'))
	        ) {
	          return (...args) => {
	            return node[prop](
	              ...args.map(i => {
	                if (typeof i === 'function') {
	                  return (child, index) => i(child.toProxy(), index)
	                } else {
	                  return i
	                }
	              })
	            )
	          }
	        } else if (prop === 'every' || prop === 'some') {
	          return cb => {
	            return node[prop]((child, ...other) =>
	              cb(child.toProxy(), ...other)
	            )
	          }
	        } else if (prop === 'root') {
	          return () => node.root().toProxy()
	        } else if (prop === 'nodes') {
	          return node.nodes.map(i => i.toProxy())
	        } else if (prop === 'first' || prop === 'last') {
	          return node[prop].toProxy()
	        } else {
	          return node[prop]
	        }
	      },

	      set(node, prop, value) {
	        if (node[prop] === value) return true
	        node[prop] = value;
	        if (prop === 'name' || prop === 'params' || prop === 'selector') {
	          node.markDirty();
	        }
	        return true
	      }
	    }
	  }

	  index(child) {
	    if (typeof child === 'number') return child
	    if (child.proxyOf) child = child.proxyOf;
	    return this.proxyOf.nodes.indexOf(child)
	  }

	  insertAfter(exist, add) {
	    let existIndex = this.index(exist);
	    let nodes = this.normalize(add, this.proxyOf.nodes[existIndex]).reverse();
	    existIndex = this.index(exist);
	    for (let node of nodes) this.proxyOf.nodes.splice(existIndex + 1, 0, node);

	    let index;
	    for (let id in this.indexes) {
	      index = this.indexes[id];
	      if (existIndex < index) {
	        this.indexes[id] = index + nodes.length;
	      }
	    }

	    this.markDirty();

	    return this
	  }

	  insertBefore(exist, add) {
	    let existIndex = this.index(exist);
	    let type = existIndex === 0 ? 'prepend' : false;
	    let nodes = this.normalize(add, this.proxyOf.nodes[existIndex], type).reverse();
	    existIndex = this.index(exist);
	    for (let node of nodes) this.proxyOf.nodes.splice(existIndex, 0, node);

	    let index;
	    for (let id in this.indexes) {
	      index = this.indexes[id];
	      if (existIndex <= index) {
	        this.indexes[id] = index + nodes.length;
	      }
	    }

	    this.markDirty();

	    return this
	  }

	  normalize(nodes, sample) {
	    if (typeof nodes === 'string') {
	      nodes = cleanSource(parse(nodes).nodes);
	    } else if (typeof nodes === 'undefined') {
	      nodes = [];
	    } else if (Array.isArray(nodes)) {
	      nodes = nodes.slice(0);
	      for (let i of nodes) {
	        if (i.parent) i.parent.removeChild(i, 'ignore');
	      }
	    } else if (nodes.type === 'root' && this.type !== 'document') {
	      nodes = nodes.nodes.slice(0);
	      for (let i of nodes) {
	        if (i.parent) i.parent.removeChild(i, 'ignore');
	      }
	    } else if (nodes.type) {
	      nodes = [nodes];
	    } else if (nodes.prop) {
	      if (typeof nodes.value === 'undefined') {
	        throw new Error('Value field is missed in node creation')
	      } else if (typeof nodes.value !== 'string') {
	        nodes.value = String(nodes.value);
	      }
	      nodes = [new Declaration(nodes)];
	    } else if (nodes.selector) {
	      nodes = [new Rule(nodes)];
	    } else if (nodes.name) {
	      nodes = [new AtRule(nodes)];
	    } else if (nodes.text) {
	      nodes = [new Comment(nodes)];
	    } else {
	      throw new Error('Unknown node type in node creation')
	    }

	    let processed = nodes.map(i => {
	      /* c8 ignore next */
	      if (!i[my]) Container.rebuild(i);
	      i = i.proxyOf;
	      if (i.parent) i.parent.removeChild(i);
	      if (i[isClean]) markDirtyUp(i);
	      if (typeof i.raws.before === 'undefined') {
	        if (sample && typeof sample.raws.before !== 'undefined') {
	          i.raws.before = sample.raws.before.replace(/\S/g, '');
	        }
	      }
	      i.parent = this.proxyOf;
	      return i
	    });

	    return processed
	  }

	  prepend(...children) {
	    children = children.reverse();
	    for (let child of children) {
	      let nodes = this.normalize(child, this.first, 'prepend').reverse();
	      for (let node of nodes) this.proxyOf.nodes.unshift(node);
	      for (let id in this.indexes) {
	        this.indexes[id] = this.indexes[id] + nodes.length;
	      }
	    }

	    this.markDirty();

	    return this
	  }

	  push(child) {
	    child.parent = this;
	    this.proxyOf.nodes.push(child);
	    return this
	  }

	  removeAll() {
	    for (let node of this.proxyOf.nodes) node.parent = undefined;
	    this.proxyOf.nodes = [];

	    this.markDirty();

	    return this
	  }

	  removeChild(child) {
	    child = this.index(child);
	    this.proxyOf.nodes[child].parent = undefined;
	    this.proxyOf.nodes.splice(child, 1);

	    let index;
	    for (let id in this.indexes) {
	      index = this.indexes[id];
	      if (index >= child) {
	        this.indexes[id] = index - 1;
	      }
	    }

	    this.markDirty();

	    return this
	  }

	  replaceValues(pattern, opts, callback) {
	    if (!callback) {
	      callback = opts;
	      opts = {};
	    }

	    this.walkDecls(decl => {
	      if (opts.props && !opts.props.includes(decl.prop)) return
	      if (opts.fast && !decl.value.includes(opts.fast)) return

	      decl.value = decl.value.replace(pattern, callback);
	    });

	    this.markDirty();

	    return this
	  }

	  some(condition) {
	    return this.nodes.some(condition)
	  }

	  walk(callback) {
	    return this.each((child, i) => {
	      let result;
	      try {
	        result = callback(child, i);
	      } catch (e) {
	        throw child.addToError(e)
	      }
	      if (result !== false && child.walk) {
	        result = child.walk(callback);
	      }

	      return result
	    })
	  }

	  walkAtRules(name, callback) {
	    if (!callback) {
	      callback = name;
	      return this.walk((child, i) => {
	        if (child.type === 'atrule') {
	          return callback(child, i)
	        }
	      })
	    }
	    if (name instanceof RegExp) {
	      return this.walk((child, i) => {
	        if (child.type === 'atrule' && name.test(child.name)) {
	          return callback(child, i)
	        }
	      })
	    }
	    return this.walk((child, i) => {
	      if (child.type === 'atrule' && child.name === name) {
	        return callback(child, i)
	      }
	    })
	  }

	  walkComments(callback) {
	    return this.walk((child, i) => {
	      if (child.type === 'comment') {
	        return callback(child, i)
	      }
	    })
	  }

	  walkDecls(prop, callback) {
	    if (!callback) {
	      callback = prop;
	      return this.walk((child, i) => {
	        if (child.type === 'decl') {
	          return callback(child, i)
	        }
	      })
	    }
	    if (prop instanceof RegExp) {
	      return this.walk((child, i) => {
	        if (child.type === 'decl' && prop.test(child.prop)) {
	          return callback(child, i)
	        }
	      })
	    }
	    return this.walk((child, i) => {
	      if (child.type === 'decl' && child.prop === prop) {
	        return callback(child, i)
	      }
	    })
	  }

	  walkRules(selector, callback) {
	    if (!callback) {
	      callback = selector;

	      return this.walk((child, i) => {
	        if (child.type === 'rule') {
	          return callback(child, i)
	        }
	      })
	    }
	    if (selector instanceof RegExp) {
	      return this.walk((child, i) => {
	        if (child.type === 'rule' && selector.test(child.selector)) {
	          return callback(child, i)
	        }
	      })
	    }
	    return this.walk((child, i) => {
	      if (child.type === 'rule' && child.selector === selector) {
	        return callback(child, i)
	      }
	    })
	  }

	  get first() {
	    if (!this.proxyOf.nodes) return undefined
	    return this.proxyOf.nodes[0]
	  }

	  get last() {
	    if (!this.proxyOf.nodes) return undefined
	    return this.proxyOf.nodes[this.proxyOf.nodes.length - 1]
	  }
	}

	Container.registerParse = dependant => {
	  parse = dependant;
	};

	Container.registerRule = dependant => {
	  Rule = dependant;
	};

	Container.registerAtRule = dependant => {
	  AtRule = dependant;
	};

	Container.registerRoot = dependant => {
	  Root = dependant;
	};

	container = Container;
	Container.default = Container;

	/* c8 ignore start */
	Container.rebuild = node => {
	  if (node.type === 'atrule') {
	    Object.setPrototypeOf(node, AtRule.prototype);
	  } else if (node.type === 'rule') {
	    Object.setPrototypeOf(node, Rule.prototype);
	  } else if (node.type === 'decl') {
	    Object.setPrototypeOf(node, Declaration.prototype);
	  } else if (node.type === 'comment') {
	    Object.setPrototypeOf(node, Comment.prototype);
	  } else if (node.type === 'root') {
	    Object.setPrototypeOf(node, Root.prototype);
	  }

	  node[my] = true;

	  if (node.nodes) {
	    node.nodes.forEach(child => {
	      Container.rebuild(child);
	    });
	  }
	};
	/* c8 ignore stop */
	return container;
}

var document$1;
var hasRequiredDocument;

function requireDocument () {
	if (hasRequiredDocument) return document$1;
	hasRequiredDocument = 1;

	let Container = requireContainer();

	let LazyResult, Processor;

	class Document extends Container {
	  constructor(defaults) {
	    // type needs to be passed to super, otherwise child roots won't be normalized correctly
	    super({ type: 'document', ...defaults });

	    if (!this.nodes) {
	      this.nodes = [];
	    }
	  }

	  toResult(opts = {}) {
	    let lazy = new LazyResult(new Processor(), this, opts);

	    return lazy.stringify()
	  }
	}

	Document.registerLazyResult = dependant => {
	  LazyResult = dependant;
	};

	Document.registerProcessor = dependant => {
	  Processor = dependant;
	};

	document$1 = Document;
	Document.default = Document;
	return document$1;
}

/* eslint-disable no-console */

var warnOnce;
var hasRequiredWarnOnce;

function requireWarnOnce () {
	if (hasRequiredWarnOnce) return warnOnce;
	hasRequiredWarnOnce = 1;

	let printed = {};

	warnOnce = function warnOnce(message) {
	  if (printed[message]) return
	  printed[message] = true;

	  if (typeof console !== 'undefined' && console.warn) {
	    console.warn(message);
	  }
	};
	return warnOnce;
}

var warning;
var hasRequiredWarning;

function requireWarning () {
	if (hasRequiredWarning) return warning;
	hasRequiredWarning = 1;

	class Warning {
	  constructor(text, opts = {}) {
	    this.type = 'warning';
	    this.text = text;

	    if (opts.node && opts.node.source) {
	      let range = opts.node.rangeBy(opts);
	      this.line = range.start.line;
	      this.column = range.start.column;
	      this.endLine = range.end.line;
	      this.endColumn = range.end.column;
	    }

	    for (let opt in opts) this[opt] = opts[opt];
	  }

	  toString() {
	    if (this.node) {
	      return this.node.error(this.text, {
	        index: this.index,
	        plugin: this.plugin,
	        word: this.word
	      }).message
	    }

	    if (this.plugin) {
	      return this.plugin + ': ' + this.text
	    }

	    return this.text
	  }
	}

	warning = Warning;
	Warning.default = Warning;
	return warning;
}

var result;
var hasRequiredResult;

function requireResult () {
	if (hasRequiredResult) return result;
	hasRequiredResult = 1;

	let Warning = requireWarning();

	class Result {
	  constructor(processor, root, opts) {
	    this.processor = processor;
	    this.messages = [];
	    this.root = root;
	    this.opts = opts;
	    this.css = undefined;
	    this.map = undefined;
	  }

	  toString() {
	    return this.css
	  }

	  warn(text, opts = {}) {
	    if (!opts.plugin) {
	      if (this.lastPlugin && this.lastPlugin.postcssPlugin) {
	        opts.plugin = this.lastPlugin.postcssPlugin;
	      }
	    }

	    let warning = new Warning(text, opts);
	    this.messages.push(warning);

	    return warning
	  }

	  warnings() {
	    return this.messages.filter(i => i.type === 'warning')
	  }

	  get content() {
	    return this.css
	  }
	}

	result = Result;
	Result.default = Result;
	return result;
}

var atRule;
var hasRequiredAtRule;

function requireAtRule () {
	if (hasRequiredAtRule) return atRule;
	hasRequiredAtRule = 1;

	let Container = requireContainer();

	class AtRule extends Container {
	  constructor(defaults) {
	    super(defaults);
	    this.type = 'atrule';
	  }

	  append(...children) {
	    if (!this.proxyOf.nodes) this.nodes = [];
	    return super.append(...children)
	  }

	  prepend(...children) {
	    if (!this.proxyOf.nodes) this.nodes = [];
	    return super.prepend(...children)
	  }
	}

	atRule = AtRule;
	AtRule.default = AtRule;

	Container.registerAtRule(AtRule);
	return atRule;
}

var root;
var hasRequiredRoot;

function requireRoot () {
	if (hasRequiredRoot) return root;
	hasRequiredRoot = 1;

	let Container = requireContainer();

	let LazyResult, Processor;

	class Root extends Container {
	  constructor(defaults) {
	    super(defaults);
	    this.type = 'root';
	    if (!this.nodes) this.nodes = [];
	  }

	  normalize(child, sample, type) {
	    let nodes = super.normalize(child);

	    if (sample) {
	      if (type === 'prepend') {
	        if (this.nodes.length > 1) {
	          sample.raws.before = this.nodes[1].raws.before;
	        } else {
	          delete sample.raws.before;
	        }
	      } else if (this.first !== sample) {
	        for (let node of nodes) {
	          node.raws.before = sample.raws.before;
	        }
	      }
	    }

	    return nodes
	  }

	  removeChild(child, ignore) {
	    let index = this.index(child);

	    if (!ignore && index === 0 && this.nodes.length > 1) {
	      this.nodes[1].raws.before = this.nodes[index].raws.before;
	    }

	    return super.removeChild(child)
	  }

	  toResult(opts = {}) {
	    let lazy = new LazyResult(new Processor(), this, opts);
	    return lazy.stringify()
	  }
	}

	Root.registerLazyResult = dependant => {
	  LazyResult = dependant;
	};

	Root.registerProcessor = dependant => {
	  Processor = dependant;
	};

	root = Root;
	Root.default = Root;

	Container.registerRoot(Root);
	return root;
}

var list_1;
var hasRequiredList;

function requireList () {
	if (hasRequiredList) return list_1;
	hasRequiredList = 1;

	let list = {
	  comma(string) {
	    return list.split(string, [','], true)
	  },

	  space(string) {
	    let spaces = [' ', '\n', '\t'];
	    return list.split(string, spaces)
	  },

	  split(string, separators, last) {
	    let array = [];
	    let current = '';
	    let split = false;

	    let func = 0;
	    let inQuote = false;
	    let prevQuote = '';
	    let escape = false;

	    for (let letter of string) {
	      if (escape) {
	        escape = false;
	      } else if (letter === '\\') {
	        escape = true;
	      } else if (inQuote) {
	        if (letter === prevQuote) {
	          inQuote = false;
	        }
	      } else if (letter === '"' || letter === "'") {
	        inQuote = true;
	        prevQuote = letter;
	      } else if (letter === '(') {
	        func += 1;
	      } else if (letter === ')') {
	        if (func > 0) func -= 1;
	      } else if (func === 0) {
	        if (separators.includes(letter)) split = true;
	      }

	      if (split) {
	        if (current !== '') array.push(current.trim());
	        current = '';
	        split = false;
	      } else {
	        current += letter;
	      }
	    }

	    if (last || current !== '') array.push(current.trim());
	    return array
	  }
	};

	list_1 = list;
	list.default = list;
	return list_1;
}

var rule;
var hasRequiredRule;

function requireRule () {
	if (hasRequiredRule) return rule;
	hasRequiredRule = 1;

	let Container = requireContainer();
	let list = requireList();

	class Rule extends Container {
	  constructor(defaults) {
	    super(defaults);
	    this.type = 'rule';
	    if (!this.nodes) this.nodes = [];
	  }

	  get selectors() {
	    return list.comma(this.selector)
	  }

	  set selectors(values) {
	    let match = this.selector ? this.selector.match(/,\s*/) : null;
	    let sep = match ? match[0] : ',' + this.raw('between', 'beforeOpen');
	    this.selector = values.join(sep);
	  }
	}

	rule = Rule;
	Rule.default = Rule;

	Container.registerRule(Rule);
	return rule;
}

var parser;
var hasRequiredParser;

function requireParser () {
	if (hasRequiredParser) return parser;
	hasRequiredParser = 1;

	let Declaration = requireDeclaration();
	let tokenizer = requireTokenize();
	let Comment = requireComment();
	let AtRule = requireAtRule();
	let Root = requireRoot();
	let Rule = requireRule();

	const SAFE_COMMENT_NEIGHBOR = {
	  empty: true,
	  space: true
	};

	function findLastWithPosition(tokens) {
	  for (let i = tokens.length - 1; i >= 0; i--) {
	    let token = tokens[i];
	    let pos = token[3] || token[2];
	    if (pos) return pos
	  }
	}

	class Parser {
	  constructor(input) {
	    this.input = input;

	    this.root = new Root();
	    this.current = this.root;
	    this.spaces = '';
	    this.semicolon = false;

	    this.createTokenizer();
	    this.root.source = { input, start: { column: 1, line: 1, offset: 0 } };
	  }

	  atrule(token) {
	    let node = new AtRule();
	    node.name = token[1].slice(1);
	    if (node.name === '') {
	      this.unnamedAtrule(node, token);
	    }
	    this.init(node, token[2]);

	    let type;
	    let prev;
	    let shift;
	    let last = false;
	    let open = false;
	    let params = [];
	    let brackets = [];

	    while (!this.tokenizer.endOfFile()) {
	      token = this.tokenizer.nextToken();
	      type = token[0];

	      if (type === '(' || type === '[') {
	        brackets.push(type === '(' ? ')' : ']');
	      } else if (type === '{' && brackets.length > 0) {
	        brackets.push('}');
	      } else if (type === brackets[brackets.length - 1]) {
	        brackets.pop();
	      }

	      if (brackets.length === 0) {
	        if (type === ';') {
	          node.source.end = this.getPosition(token[2]);
	          node.source.end.offset++;
	          this.semicolon = true;
	          break
	        } else if (type === '{') {
	          open = true;
	          break
	        } else if (type === '}') {
	          if (params.length > 0) {
	            shift = params.length - 1;
	            prev = params[shift];
	            while (prev && prev[0] === 'space') {
	              prev = params[--shift];
	            }
	            if (prev) {
	              node.source.end = this.getPosition(prev[3] || prev[2]);
	              node.source.end.offset++;
	            }
	          }
	          this.end(token);
	          break
	        } else {
	          params.push(token);
	        }
	      } else {
	        params.push(token);
	      }

	      if (this.tokenizer.endOfFile()) {
	        last = true;
	        break
	      }
	    }

	    node.raws.between = this.spacesAndCommentsFromEnd(params);
	    if (params.length) {
	      node.raws.afterName = this.spacesAndCommentsFromStart(params);
	      this.raw(node, 'params', params);
	      if (last) {
	        token = params[params.length - 1];
	        node.source.end = this.getPosition(token[3] || token[2]);
	        node.source.end.offset++;
	        this.spaces = node.raws.between;
	        node.raws.between = '';
	      }
	    } else {
	      node.raws.afterName = '';
	      node.params = '';
	    }

	    if (open) {
	      node.nodes = [];
	      this.current = node;
	    }
	  }

	  checkMissedSemicolon(tokens) {
	    let colon = this.colon(tokens);
	    if (colon === false) return

	    let founded = 0;
	    let token;
	    for (let j = colon - 1; j >= 0; j--) {
	      token = tokens[j];
	      if (token[0] !== 'space') {
	        founded += 1;
	        if (founded === 2) break
	      }
	    }
	    // If the token is a word, e.g. `!important`, `red` or any other valid property's value.
	    // Then we need to return the colon after that word token. [3] is the "end" colon of that word.
	    // And because we need it after that one we do +1 to get the next one.
	    throw this.input.error(
	      'Missed semicolon',
	      token[0] === 'word' ? token[3] + 1 : token[2]
	    )
	  }

	  colon(tokens) {
	    let brackets = 0;
	    let token, type, prev;
	    for (let [i, element] of tokens.entries()) {
	      token = element;
	      type = token[0];

	      if (type === '(') {
	        brackets += 1;
	      }
	      if (type === ')') {
	        brackets -= 1;
	      }
	      if (brackets === 0 && type === ':') {
	        if (!prev) {
	          this.doubleColon(token);
	        } else if (prev[0] === 'word' && prev[1] === 'progid') {
	          continue
	        } else {
	          return i
	        }
	      }

	      prev = token;
	    }
	    return false
	  }

	  comment(token) {
	    let node = new Comment();
	    this.init(node, token[2]);
	    node.source.end = this.getPosition(token[3] || token[2]);
	    node.source.end.offset++;

	    let text = token[1].slice(2, -2);
	    if (/^\s*$/.test(text)) {
	      node.text = '';
	      node.raws.left = text;
	      node.raws.right = '';
	    } else {
	      let match = text.match(/^(\s*)([^]*\S)(\s*)$/);
	      node.text = match[2];
	      node.raws.left = match[1];
	      node.raws.right = match[3];
	    }
	  }

	  createTokenizer() {
	    this.tokenizer = tokenizer(this.input);
	  }

	  decl(tokens, customProperty) {
	    let node = new Declaration();
	    this.init(node, tokens[0][2]);

	    let last = tokens[tokens.length - 1];
	    if (last[0] === ';') {
	      this.semicolon = true;
	      tokens.pop();
	    }

	    node.source.end = this.getPosition(
	      last[3] || last[2] || findLastWithPosition(tokens)
	    );
	    node.source.end.offset++;

	    while (tokens[0][0] !== 'word') {
	      if (tokens.length === 1) this.unknownWord(tokens);
	      node.raws.before += tokens.shift()[1];
	    }
	    node.source.start = this.getPosition(tokens[0][2]);

	    node.prop = '';
	    while (tokens.length) {
	      let type = tokens[0][0];
	      if (type === ':' || type === 'space' || type === 'comment') {
	        break
	      }
	      node.prop += tokens.shift()[1];
	    }

	    node.raws.between = '';

	    let token;
	    while (tokens.length) {
	      token = tokens.shift();

	      if (token[0] === ':') {
	        node.raws.between += token[1];
	        break
	      } else {
	        if (token[0] === 'word' && /\w/.test(token[1])) {
	          this.unknownWord([token]);
	        }
	        node.raws.between += token[1];
	      }
	    }

	    if (node.prop[0] === '_' || node.prop[0] === '*') {
	      node.raws.before += node.prop[0];
	      node.prop = node.prop.slice(1);
	    }

	    let firstSpaces = [];
	    let next;
	    while (tokens.length) {
	      next = tokens[0][0];
	      if (next !== 'space' && next !== 'comment') break
	      firstSpaces.push(tokens.shift());
	    }

	    this.precheckMissedSemicolon(tokens);

	    for (let i = tokens.length - 1; i >= 0; i--) {
	      token = tokens[i];
	      if (token[1].toLowerCase() === '!important') {
	        node.important = true;
	        let string = this.stringFrom(tokens, i);
	        string = this.spacesFromEnd(tokens) + string;
	        if (string !== ' !important') node.raws.important = string;
	        break
	      } else if (token[1].toLowerCase() === 'important') {
	        let cache = tokens.slice(0);
	        let str = '';
	        for (let j = i; j > 0; j--) {
	          let type = cache[j][0];
	          if (str.trim().indexOf('!') === 0 && type !== 'space') {
	            break
	          }
	          str = cache.pop()[1] + str;
	        }
	        if (str.trim().indexOf('!') === 0) {
	          node.important = true;
	          node.raws.important = str;
	          tokens = cache;
	        }
	      }

	      if (token[0] !== 'space' && token[0] !== 'comment') {
	        break
	      }
	    }

	    let hasWord = tokens.some(i => i[0] !== 'space' && i[0] !== 'comment');

	    if (hasWord) {
	      node.raws.between += firstSpaces.map(i => i[1]).join('');
	      firstSpaces = [];
	    }
	    this.raw(node, 'value', firstSpaces.concat(tokens), customProperty);

	    if (node.value.includes(':') && !customProperty) {
	      this.checkMissedSemicolon(tokens);
	    }
	  }

	  doubleColon(token) {
	    throw this.input.error(
	      'Double colon',
	      { offset: token[2] },
	      { offset: token[2] + token[1].length }
	    )
	  }

	  emptyRule(token) {
	    let node = new Rule();
	    this.init(node, token[2]);
	    node.selector = '';
	    node.raws.between = '';
	    this.current = node;
	  }

	  end(token) {
	    if (this.current.nodes && this.current.nodes.length) {
	      this.current.raws.semicolon = this.semicolon;
	    }
	    this.semicolon = false;

	    this.current.raws.after = (this.current.raws.after || '') + this.spaces;
	    this.spaces = '';

	    if (this.current.parent) {
	      this.current.source.end = this.getPosition(token[2]);
	      this.current.source.end.offset++;
	      this.current = this.current.parent;
	    } else {
	      this.unexpectedClose(token);
	    }
	  }

	  endFile() {
	    if (this.current.parent) this.unclosedBlock();
	    if (this.current.nodes && this.current.nodes.length) {
	      this.current.raws.semicolon = this.semicolon;
	    }
	    this.current.raws.after = (this.current.raws.after || '') + this.spaces;
	    this.root.source.end = this.getPosition(this.tokenizer.position());
	  }

	  freeSemicolon(token) {
	    this.spaces += token[1];
	    if (this.current.nodes) {
	      let prev = this.current.nodes[this.current.nodes.length - 1];
	      if (prev && prev.type === 'rule' && !prev.raws.ownSemicolon) {
	        prev.raws.ownSemicolon = this.spaces;
	        this.spaces = '';
	      }
	    }
	  }

	  // Helpers

	  getPosition(offset) {
	    let pos = this.input.fromOffset(offset);
	    return {
	      column: pos.col,
	      line: pos.line,
	      offset
	    }
	  }

	  init(node, offset) {
	    this.current.push(node);
	    node.source = {
	      input: this.input,
	      start: this.getPosition(offset)
	    };
	    node.raws.before = this.spaces;
	    this.spaces = '';
	    if (node.type !== 'comment') this.semicolon = false;
	  }

	  other(start) {
	    let end = false;
	    let type = null;
	    let colon = false;
	    let bracket = null;
	    let brackets = [];
	    let customProperty = start[1].startsWith('--');

	    let tokens = [];
	    let token = start;
	    while (token) {
	      type = token[0];
	      tokens.push(token);

	      if (type === '(' || type === '[') {
	        if (!bracket) bracket = token;
	        brackets.push(type === '(' ? ')' : ']');
	      } else if (customProperty && colon && type === '{') {
	        if (!bracket) bracket = token;
	        brackets.push('}');
	      } else if (brackets.length === 0) {
	        if (type === ';') {
	          if (colon) {
	            this.decl(tokens, customProperty);
	            return
	          } else {
	            break
	          }
	        } else if (type === '{') {
	          this.rule(tokens);
	          return
	        } else if (type === '}') {
	          this.tokenizer.back(tokens.pop());
	          end = true;
	          break
	        } else if (type === ':') {
	          colon = true;
	        }
	      } else if (type === brackets[brackets.length - 1]) {
	        brackets.pop();
	        if (brackets.length === 0) bracket = null;
	      }

	      token = this.tokenizer.nextToken();
	    }

	    if (this.tokenizer.endOfFile()) end = true;
	    if (brackets.length > 0) this.unclosedBracket(bracket);

	    if (end && colon) {
	      if (!customProperty) {
	        while (tokens.length) {
	          token = tokens[tokens.length - 1][0];
	          if (token !== 'space' && token !== 'comment') break
	          this.tokenizer.back(tokens.pop());
	        }
	      }
	      this.decl(tokens, customProperty);
	    } else {
	      this.unknownWord(tokens);
	    }
	  }

	  parse() {
	    let token;
	    while (!this.tokenizer.endOfFile()) {
	      token = this.tokenizer.nextToken();

	      switch (token[0]) {
	        case 'space':
	          this.spaces += token[1];
	          break

	        case ';':
	          this.freeSemicolon(token);
	          break

	        case '}':
	          this.end(token);
	          break

	        case 'comment':
	          this.comment(token);
	          break

	        case 'at-word':
	          this.atrule(token);
	          break

	        case '{':
	          this.emptyRule(token);
	          break

	        default:
	          this.other(token);
	          break
	      }
	    }
	    this.endFile();
	  }

	  precheckMissedSemicolon(/* tokens */) {
	    // Hook for Safe Parser
	  }

	  raw(node, prop, tokens, customProperty) {
	    let token, type;
	    let length = tokens.length;
	    let value = '';
	    let clean = true;
	    let next, prev;

	    for (let i = 0; i < length; i += 1) {
	      token = tokens[i];
	      type = token[0];
	      if (type === 'space' && i === length - 1 && !customProperty) {
	        clean = false;
	      } else if (type === 'comment') {
	        prev = tokens[i - 1] ? tokens[i - 1][0] : 'empty';
	        next = tokens[i + 1] ? tokens[i + 1][0] : 'empty';
	        if (!SAFE_COMMENT_NEIGHBOR[prev] && !SAFE_COMMENT_NEIGHBOR[next]) {
	          if (value.slice(-1) === ',') {
	            clean = false;
	          } else {
	            value += token[1];
	          }
	        } else {
	          clean = false;
	        }
	      } else {
	        value += token[1];
	      }
	    }
	    if (!clean) {
	      let raw = tokens.reduce((all, i) => all + i[1], '');
	      node.raws[prop] = { raw, value };
	    }
	    node[prop] = value;
	  }

	  rule(tokens) {
	    tokens.pop();

	    let node = new Rule();
	    this.init(node, tokens[0][2]);

	    node.raws.between = this.spacesAndCommentsFromEnd(tokens);
	    this.raw(node, 'selector', tokens);
	    this.current = node;
	  }

	  spacesAndCommentsFromEnd(tokens) {
	    let lastTokenType;
	    let spaces = '';
	    while (tokens.length) {
	      lastTokenType = tokens[tokens.length - 1][0];
	      if (lastTokenType !== 'space' && lastTokenType !== 'comment') break
	      spaces = tokens.pop()[1] + spaces;
	    }
	    return spaces
	  }

	  // Errors

	  spacesAndCommentsFromStart(tokens) {
	    let next;
	    let spaces = '';
	    while (tokens.length) {
	      next = tokens[0][0];
	      if (next !== 'space' && next !== 'comment') break
	      spaces += tokens.shift()[1];
	    }
	    return spaces
	  }

	  spacesFromEnd(tokens) {
	    let lastTokenType;
	    let spaces = '';
	    while (tokens.length) {
	      lastTokenType = tokens[tokens.length - 1][0];
	      if (lastTokenType !== 'space') break
	      spaces = tokens.pop()[1] + spaces;
	    }
	    return spaces
	  }

	  stringFrom(tokens, from) {
	    let result = '';
	    for (let i = from; i < tokens.length; i++) {
	      result += tokens[i][1];
	    }
	    tokens.splice(from, tokens.length - from);
	    return result
	  }

	  unclosedBlock() {
	    let pos = this.current.source.start;
	    throw this.input.error('Unclosed block', pos.line, pos.column)
	  }

	  unclosedBracket(bracket) {
	    throw this.input.error(
	      'Unclosed bracket',
	      { offset: bracket[2] },
	      { offset: bracket[2] + 1 }
	    )
	  }

	  unexpectedClose(token) {
	    throw this.input.error(
	      'Unexpected }',
	      { offset: token[2] },
	      { offset: token[2] + 1 }
	    )
	  }

	  unknownWord(tokens) {
	    throw this.input.error(
	      'Unknown word',
	      { offset: tokens[0][2] },
	      { offset: tokens[0][2] + tokens[0][1].length }
	    )
	  }

	  unnamedAtrule(node, token) {
	    throw this.input.error(
	      'At-rule without name',
	      { offset: token[2] },
	      { offset: token[2] + token[1].length }
	    )
	  }
	}

	parser = Parser;
	return parser;
}

var parse_1;
var hasRequiredParse;

function requireParse () {
	if (hasRequiredParse) return parse_1;
	hasRequiredParse = 1;

	let Container = requireContainer();
	let Parser = requireParser();
	let Input = requireInput();

	function parse(css, opts) {
	  let input = new Input(css, opts);
	  let parser = new Parser(input);
	  try {
	    parser.parse();
	  } catch (e) {
	    if (process.env.NODE_ENV !== 'production') {
	      if (e.name === 'CssSyntaxError' && opts && opts.from) {
	        if (/\.scss$/i.test(opts.from)) {
	          e.message +=
	            '\nYou tried to parse SCSS with ' +
	            'the standard CSS parser; ' +
	            'try again with the postcss-scss parser';
	        } else if (/\.sass/i.test(opts.from)) {
	          e.message +=
	            '\nYou tried to parse Sass with ' +
	            'the standard CSS parser; ' +
	            'try again with the postcss-sass parser';
	        } else if (/\.less$/i.test(opts.from)) {
	          e.message +=
	            '\nYou tried to parse Less with ' +
	            'the standard CSS parser; ' +
	            'try again with the postcss-less parser';
	        }
	      }
	    }
	    throw e
	  }

	  return parser.root
	}

	parse_1 = parse;
	parse.default = parse;

	Container.registerParse(parse);
	return parse_1;
}

var lazyResult;
var hasRequiredLazyResult;

function requireLazyResult () {
	if (hasRequiredLazyResult) return lazyResult;
	hasRequiredLazyResult = 1;

	let { isClean, my } = requireSymbols();
	let MapGenerator = requireMapGenerator();
	let stringify = requireStringify();
	let Container = requireContainer();
	let Document = requireDocument();
	let warnOnce = requireWarnOnce();
	let Result = requireResult();
	let parse = requireParse();
	let Root = requireRoot();

	const TYPE_TO_CLASS_NAME = {
	  atrule: 'AtRule',
	  comment: 'Comment',
	  decl: 'Declaration',
	  document: 'Document',
	  root: 'Root',
	  rule: 'Rule'
	};

	const PLUGIN_PROPS = {
	  AtRule: true,
	  AtRuleExit: true,
	  Comment: true,
	  CommentExit: true,
	  Declaration: true,
	  DeclarationExit: true,
	  Document: true,
	  DocumentExit: true,
	  Once: true,
	  OnceExit: true,
	  postcssPlugin: true,
	  prepare: true,
	  Root: true,
	  RootExit: true,
	  Rule: true,
	  RuleExit: true
	};

	const NOT_VISITORS = {
	  Once: true,
	  postcssPlugin: true,
	  prepare: true
	};

	const CHILDREN = 0;

	function isPromise(obj) {
	  return typeof obj === 'object' && typeof obj.then === 'function'
	}

	function getEvents(node) {
	  let key = false;
	  let type = TYPE_TO_CLASS_NAME[node.type];
	  if (node.type === 'decl') {
	    key = node.prop.toLowerCase();
	  } else if (node.type === 'atrule') {
	    key = node.name.toLowerCase();
	  }

	  if (key && node.append) {
	    return [
	      type,
	      type + '-' + key,
	      CHILDREN,
	      type + 'Exit',
	      type + 'Exit-' + key
	    ]
	  } else if (key) {
	    return [type, type + '-' + key, type + 'Exit', type + 'Exit-' + key]
	  } else if (node.append) {
	    return [type, CHILDREN, type + 'Exit']
	  } else {
	    return [type, type + 'Exit']
	  }
	}

	function toStack(node) {
	  let events;
	  if (node.type === 'document') {
	    events = ['Document', CHILDREN, 'DocumentExit'];
	  } else if (node.type === 'root') {
	    events = ['Root', CHILDREN, 'RootExit'];
	  } else {
	    events = getEvents(node);
	  }

	  return {
	    eventIndex: 0,
	    events,
	    iterator: 0,
	    node,
	    visitorIndex: 0,
	    visitors: []
	  }
	}

	function cleanMarks(node) {
	  node[isClean] = false;
	  if (node.nodes) node.nodes.forEach(i => cleanMarks(i));
	  return node
	}

	let postcss = {};

	class LazyResult {
	  constructor(processor, css, opts) {
	    this.stringified = false;
	    this.processed = false;

	    let root;
	    if (
	      typeof css === 'object' &&
	      css !== null &&
	      (css.type === 'root' || css.type === 'document')
	    ) {
	      root = cleanMarks(css);
	    } else if (css instanceof LazyResult || css instanceof Result) {
	      root = cleanMarks(css.root);
	      if (css.map) {
	        if (typeof opts.map === 'undefined') opts.map = {};
	        if (!opts.map.inline) opts.map.inline = false;
	        opts.map.prev = css.map;
	      }
	    } else {
	      let parser = parse;
	      if (opts.syntax) parser = opts.syntax.parse;
	      if (opts.parser) parser = opts.parser;
	      if (parser.parse) parser = parser.parse;

	      try {
	        root = parser(css, opts);
	      } catch (error) {
	        this.processed = true;
	        this.error = error;
	      }

	      if (root && !root[my]) {
	        /* c8 ignore next 2 */
	        Container.rebuild(root);
	      }
	    }

	    this.result = new Result(processor, root, opts);
	    this.helpers = { ...postcss, postcss, result: this.result };
	    this.plugins = this.processor.plugins.map(plugin => {
	      if (typeof plugin === 'object' && plugin.prepare) {
	        return { ...plugin, ...plugin.prepare(this.result) }
	      } else {
	        return plugin
	      }
	    });
	  }

	  async() {
	    if (this.error) return Promise.reject(this.error)
	    if (this.processed) return Promise.resolve(this.result)
	    if (!this.processing) {
	      this.processing = this.runAsync();
	    }
	    return this.processing
	  }

	  catch(onRejected) {
	    return this.async().catch(onRejected)
	  }

	  finally(onFinally) {
	    return this.async().then(onFinally, onFinally)
	  }

	  getAsyncError() {
	    throw new Error('Use process(css).then(cb) to work with async plugins')
	  }

	  handleError(error, node) {
	    let plugin = this.result.lastPlugin;
	    try {
	      if (node) node.addToError(error);
	      this.error = error;
	      if (error.name === 'CssSyntaxError' && !error.plugin) {
	        error.plugin = plugin.postcssPlugin;
	        error.setMessage();
	      } else if (plugin.postcssVersion) {
	        if (process.env.NODE_ENV !== 'production') {
	          let pluginName = plugin.postcssPlugin;
	          let pluginVer = plugin.postcssVersion;
	          let runtimeVer = this.result.processor.version;
	          let a = pluginVer.split('.');
	          let b = runtimeVer.split('.');

	          if (a[0] !== b[0] || parseInt(a[1]) > parseInt(b[1])) {
	            // eslint-disable-next-line no-console
	            console.error(
	              'Unknown error from PostCSS plugin. Your current PostCSS ' +
	                'version is ' +
	                runtimeVer +
	                ', but ' +
	                pluginName +
	                ' uses ' +
	                pluginVer +
	                '. Perhaps this is the source of the error below.'
	            );
	          }
	        }
	      }
	    } catch (err) {
	      /* c8 ignore next 3 */
	      // eslint-disable-next-line no-console
	      if (console && console.error) console.error(err);
	    }
	    return error
	  }

	  prepareVisitors() {
	    this.listeners = {};
	    let add = (plugin, type, cb) => {
	      if (!this.listeners[type]) this.listeners[type] = [];
	      this.listeners[type].push([plugin, cb]);
	    };
	    for (let plugin of this.plugins) {
	      if (typeof plugin === 'object') {
	        for (let event in plugin) {
	          if (!PLUGIN_PROPS[event] && /^[A-Z]/.test(event)) {
	            throw new Error(
	              `Unknown event ${event} in ${plugin.postcssPlugin}. ` +
	                `Try to update PostCSS (${this.processor.version} now).`
	            )
	          }
	          if (!NOT_VISITORS[event]) {
	            if (typeof plugin[event] === 'object') {
	              for (let filter in plugin[event]) {
	                if (filter === '*') {
	                  add(plugin, event, plugin[event][filter]);
	                } else {
	                  add(
	                    plugin,
	                    event + '-' + filter.toLowerCase(),
	                    plugin[event][filter]
	                  );
	                }
	              }
	            } else if (typeof plugin[event] === 'function') {
	              add(plugin, event, plugin[event]);
	            }
	          }
	        }
	      }
	    }
	    this.hasListener = Object.keys(this.listeners).length > 0;
	  }

	  async runAsync() {
	    this.plugin = 0;
	    for (let i = 0; i < this.plugins.length; i++) {
	      let plugin = this.plugins[i];
	      let promise = this.runOnRoot(plugin);
	      if (isPromise(promise)) {
	        try {
	          await promise;
	        } catch (error) {
	          throw this.handleError(error)
	        }
	      }
	    }

	    this.prepareVisitors();
	    if (this.hasListener) {
	      let root = this.result.root;
	      while (!root[isClean]) {
	        root[isClean] = true;
	        let stack = [toStack(root)];
	        while (stack.length > 0) {
	          let promise = this.visitTick(stack);
	          if (isPromise(promise)) {
	            try {
	              await promise;
	            } catch (e) {
	              let node = stack[stack.length - 1].node;
	              throw this.handleError(e, node)
	            }
	          }
	        }
	      }

	      if (this.listeners.OnceExit) {
	        for (let [plugin, visitor] of this.listeners.OnceExit) {
	          this.result.lastPlugin = plugin;
	          try {
	            if (root.type === 'document') {
	              let roots = root.nodes.map(subRoot =>
	                visitor(subRoot, this.helpers)
	              );

	              await Promise.all(roots);
	            } else {
	              await visitor(root, this.helpers);
	            }
	          } catch (e) {
	            throw this.handleError(e)
	          }
	        }
	      }
	    }

	    this.processed = true;
	    return this.stringify()
	  }

	  runOnRoot(plugin) {
	    this.result.lastPlugin = plugin;
	    try {
	      if (typeof plugin === 'object' && plugin.Once) {
	        if (this.result.root.type === 'document') {
	          let roots = this.result.root.nodes.map(root =>
	            plugin.Once(root, this.helpers)
	          );

	          if (isPromise(roots[0])) {
	            return Promise.all(roots)
	          }

	          return roots
	        }

	        return plugin.Once(this.result.root, this.helpers)
	      } else if (typeof plugin === 'function') {
	        return plugin(this.result.root, this.result)
	      }
	    } catch (error) {
	      throw this.handleError(error)
	    }
	  }

	  stringify() {
	    if (this.error) throw this.error
	    if (this.stringified) return this.result
	    this.stringified = true;

	    this.sync();

	    let opts = this.result.opts;
	    let str = stringify;
	    if (opts.syntax) str = opts.syntax.stringify;
	    if (opts.stringifier) str = opts.stringifier;
	    if (str.stringify) str = str.stringify;

	    let map = new MapGenerator(str, this.result.root, this.result.opts);
	    let data = map.generate();
	    this.result.css = data[0];
	    this.result.map = data[1];

	    return this.result
	  }

	  sync() {
	    if (this.error) throw this.error
	    if (this.processed) return this.result
	    this.processed = true;

	    if (this.processing) {
	      throw this.getAsyncError()
	    }

	    for (let plugin of this.plugins) {
	      let promise = this.runOnRoot(plugin);
	      if (isPromise(promise)) {
	        throw this.getAsyncError()
	      }
	    }

	    this.prepareVisitors();
	    if (this.hasListener) {
	      let root = this.result.root;
	      while (!root[isClean]) {
	        root[isClean] = true;
	        this.walkSync(root);
	      }
	      if (this.listeners.OnceExit) {
	        if (root.type === 'document') {
	          for (let subRoot of root.nodes) {
	            this.visitSync(this.listeners.OnceExit, subRoot);
	          }
	        } else {
	          this.visitSync(this.listeners.OnceExit, root);
	        }
	      }
	    }

	    return this.result
	  }

	  then(onFulfilled, onRejected) {
	    if (process.env.NODE_ENV !== 'production') {
	      if (!('from' in this.opts)) {
	        warnOnce(
	          'Without `from` option PostCSS could generate wrong source map ' +
	            'and will not find Browserslist config. Set it to CSS file path ' +
	            'or to `undefined` to prevent this warning.'
	        );
	      }
	    }
	    return this.async().then(onFulfilled, onRejected)
	  }

	  toString() {
	    return this.css
	  }

	  visitSync(visitors, node) {
	    for (let [plugin, visitor] of visitors) {
	      this.result.lastPlugin = plugin;
	      let promise;
	      try {
	        promise = visitor(node, this.helpers);
	      } catch (e) {
	        throw this.handleError(e, node.proxyOf)
	      }
	      if (node.type !== 'root' && node.type !== 'document' && !node.parent) {
	        return true
	      }
	      if (isPromise(promise)) {
	        throw this.getAsyncError()
	      }
	    }
	  }

	  visitTick(stack) {
	    let visit = stack[stack.length - 1];
	    let { node, visitors } = visit;

	    if (node.type !== 'root' && node.type !== 'document' && !node.parent) {
	      stack.pop();
	      return
	    }

	    if (visitors.length > 0 && visit.visitorIndex < visitors.length) {
	      let [plugin, visitor] = visitors[visit.visitorIndex];
	      visit.visitorIndex += 1;
	      if (visit.visitorIndex === visitors.length) {
	        visit.visitors = [];
	        visit.visitorIndex = 0;
	      }
	      this.result.lastPlugin = plugin;
	      try {
	        return visitor(node.toProxy(), this.helpers)
	      } catch (e) {
	        throw this.handleError(e, node)
	      }
	    }

	    if (visit.iterator !== 0) {
	      let iterator = visit.iterator;
	      let child;
	      while ((child = node.nodes[node.indexes[iterator]])) {
	        node.indexes[iterator] += 1;
	        if (!child[isClean]) {
	          child[isClean] = true;
	          stack.push(toStack(child));
	          return
	        }
	      }
	      visit.iterator = 0;
	      delete node.indexes[iterator];
	    }

	    let events = visit.events;
	    while (visit.eventIndex < events.length) {
	      let event = events[visit.eventIndex];
	      visit.eventIndex += 1;
	      if (event === CHILDREN) {
	        if (node.nodes && node.nodes.length) {
	          node[isClean] = true;
	          visit.iterator = node.getIterator();
	        }
	        return
	      } else if (this.listeners[event]) {
	        visit.visitors = this.listeners[event];
	        return
	      }
	    }
	    stack.pop();
	  }

	  walkSync(node) {
	    node[isClean] = true;
	    let events = getEvents(node);
	    for (let event of events) {
	      if (event === CHILDREN) {
	        if (node.nodes) {
	          node.each(child => {
	            if (!child[isClean]) this.walkSync(child);
	          });
	        }
	      } else {
	        let visitors = this.listeners[event];
	        if (visitors) {
	          if (this.visitSync(visitors, node.toProxy())) return
	        }
	      }
	    }
	  }

	  warnings() {
	    return this.sync().warnings()
	  }

	  get content() {
	    return this.stringify().content
	  }

	  get css() {
	    return this.stringify().css
	  }

	  get map() {
	    return this.stringify().map
	  }

	  get messages() {
	    return this.sync().messages
	  }

	  get opts() {
	    return this.result.opts
	  }

	  get processor() {
	    return this.result.processor
	  }

	  get root() {
	    return this.sync().root
	  }

	  get [Symbol.toStringTag]() {
	    return 'LazyResult'
	  }
	}

	LazyResult.registerPostcss = dependant => {
	  postcss = dependant;
	};

	lazyResult = LazyResult;
	LazyResult.default = LazyResult;

	Root.registerLazyResult(LazyResult);
	Document.registerLazyResult(LazyResult);
	return lazyResult;
}

var noWorkResult;
var hasRequiredNoWorkResult;

function requireNoWorkResult () {
	if (hasRequiredNoWorkResult) return noWorkResult;
	hasRequiredNoWorkResult = 1;

	let MapGenerator = requireMapGenerator();
	let stringify = requireStringify();
	let warnOnce = requireWarnOnce();
	let parse = requireParse();
	const Result = requireResult();

	class NoWorkResult {
	  constructor(processor, css, opts) {
	    css = css.toString();
	    this.stringified = false;

	    this._processor = processor;
	    this._css = css;
	    this._opts = opts;
	    this._map = undefined;
	    let root;

	    let str = stringify;
	    this.result = new Result(this._processor, root, this._opts);
	    this.result.css = css;

	    let self = this;
	    Object.defineProperty(this.result, 'root', {
	      get() {
	        return self.root
	      }
	    });

	    let map = new MapGenerator(str, root, this._opts, css);
	    if (map.isMap()) {
	      let [generatedCSS, generatedMap] = map.generate();
	      if (generatedCSS) {
	        this.result.css = generatedCSS;
	      }
	      if (generatedMap) {
	        this.result.map = generatedMap;
	      }
	    } else {
	      map.clearAnnotation();
	      this.result.css = map.css;
	    }
	  }

	  async() {
	    if (this.error) return Promise.reject(this.error)
	    return Promise.resolve(this.result)
	  }

	  catch(onRejected) {
	    return this.async().catch(onRejected)
	  }

	  finally(onFinally) {
	    return this.async().then(onFinally, onFinally)
	  }

	  sync() {
	    if (this.error) throw this.error
	    return this.result
	  }

	  then(onFulfilled, onRejected) {
	    if (process.env.NODE_ENV !== 'production') {
	      if (!('from' in this._opts)) {
	        warnOnce(
	          'Without `from` option PostCSS could generate wrong source map ' +
	            'and will not find Browserslist config. Set it to CSS file path ' +
	            'or to `undefined` to prevent this warning.'
	        );
	      }
	    }

	    return this.async().then(onFulfilled, onRejected)
	  }

	  toString() {
	    return this._css
	  }

	  warnings() {
	    return []
	  }

	  get content() {
	    return this.result.css
	  }

	  get css() {
	    return this.result.css
	  }

	  get map() {
	    return this.result.map
	  }

	  get messages() {
	    return []
	  }

	  get opts() {
	    return this.result.opts
	  }

	  get processor() {
	    return this.result.processor
	  }

	  get root() {
	    if (this._root) {
	      return this._root
	    }

	    let root;
	    let parser = parse;

	    try {
	      root = parser(this._css, this._opts);
	    } catch (error) {
	      this.error = error;
	    }

	    if (this.error) {
	      throw this.error
	    } else {
	      this._root = root;
	      return root
	    }
	  }

	  get [Symbol.toStringTag]() {
	    return 'NoWorkResult'
	  }
	}

	noWorkResult = NoWorkResult;
	NoWorkResult.default = NoWorkResult;
	return noWorkResult;
}

var processor;
var hasRequiredProcessor;

function requireProcessor () {
	if (hasRequiredProcessor) return processor;
	hasRequiredProcessor = 1;

	let NoWorkResult = requireNoWorkResult();
	let LazyResult = requireLazyResult();
	let Document = requireDocument();
	let Root = requireRoot();

	class Processor {
	  constructor(plugins = []) {
	    this.version = '8.4.38';
	    this.plugins = this.normalize(plugins);
	  }

	  normalize(plugins) {
	    let normalized = [];
	    for (let i of plugins) {
	      if (i.postcss === true) {
	        i = i();
	      } else if (i.postcss) {
	        i = i.postcss;
	      }

	      if (typeof i === 'object' && Array.isArray(i.plugins)) {
	        normalized = normalized.concat(i.plugins);
	      } else if (typeof i === 'object' && i.postcssPlugin) {
	        normalized.push(i);
	      } else if (typeof i === 'function') {
	        normalized.push(i);
	      } else if (typeof i === 'object' && (i.parse || i.stringify)) {
	        if (process.env.NODE_ENV !== 'production') {
	          throw new Error(
	            'PostCSS syntaxes cannot be used as plugins. Instead, please use ' +
	              'one of the syntax/parser/stringifier options as outlined ' +
	              'in your PostCSS runner documentation.'
	          )
	        }
	      } else {
	        throw new Error(i + ' is not a PostCSS plugin')
	      }
	    }
	    return normalized
	  }

	  process(css, opts = {}) {
	    if (
	      !this.plugins.length &&
	      !opts.parser &&
	      !opts.stringifier &&
	      !opts.syntax
	    ) {
	      return new NoWorkResult(this, css, opts)
	    } else {
	      return new LazyResult(this, css, opts)
	    }
	  }

	  use(plugin) {
	    this.plugins = this.plugins.concat(this.normalize([plugin]));
	    return this
	  }
	}

	processor = Processor;
	Processor.default = Processor;

	Root.registerProcessor(Processor);
	Document.registerProcessor(Processor);
	return processor;
}

var fromJSON_1;
var hasRequiredFromJSON;

function requireFromJSON () {
	if (hasRequiredFromJSON) return fromJSON_1;
	hasRequiredFromJSON = 1;

	let Declaration = requireDeclaration();
	let PreviousMap = requirePreviousMap();
	let Comment = requireComment();
	let AtRule = requireAtRule();
	let Input = requireInput();
	let Root = requireRoot();
	let Rule = requireRule();

	function fromJSON(json, inputs) {
	  if (Array.isArray(json)) return json.map(n => fromJSON(n))

	  let { inputs: ownInputs, ...defaults } = json;
	  if (ownInputs) {
	    inputs = [];
	    for (let input of ownInputs) {
	      let inputHydrated = { ...input, __proto__: Input.prototype };
	      if (inputHydrated.map) {
	        inputHydrated.map = {
	          ...inputHydrated.map,
	          __proto__: PreviousMap.prototype
	        };
	      }
	      inputs.push(inputHydrated);
	    }
	  }
	  if (defaults.nodes) {
	    defaults.nodes = json.nodes.map(n => fromJSON(n, inputs));
	  }
	  if (defaults.source) {
	    let { inputId, ...source } = defaults.source;
	    defaults.source = source;
	    if (inputId != null) {
	      defaults.source.input = inputs[inputId];
	    }
	  }
	  if (defaults.type === 'root') {
	    return new Root(defaults)
	  } else if (defaults.type === 'decl') {
	    return new Declaration(defaults)
	  } else if (defaults.type === 'rule') {
	    return new Rule(defaults)
	  } else if (defaults.type === 'comment') {
	    return new Comment(defaults)
	  } else if (defaults.type === 'atrule') {
	    return new AtRule(defaults)
	  } else {
	    throw new Error('Unknown node type: ' + json.type)
	  }
	}

	fromJSON_1 = fromJSON;
	fromJSON.default = fromJSON;
	return fromJSON_1;
}

var postcss_1;
var hasRequiredPostcss;

function requirePostcss () {
	if (hasRequiredPostcss) return postcss_1;
	hasRequiredPostcss = 1;

	let CssSyntaxError = requireCssSyntaxError();
	let Declaration = requireDeclaration();
	let LazyResult = requireLazyResult();
	let Container = requireContainer();
	let Processor = requireProcessor();
	let stringify = requireStringify();
	let fromJSON = requireFromJSON();
	let Document = requireDocument();
	let Warning = requireWarning();
	let Comment = requireComment();
	let AtRule = requireAtRule();
	let Result = requireResult();
	let Input = requireInput();
	let parse = requireParse();
	let list = requireList();
	let Rule = requireRule();
	let Root = requireRoot();
	let Node = requireNode();

	function postcss(...plugins) {
	  if (plugins.length === 1 && Array.isArray(plugins[0])) {
	    plugins = plugins[0];
	  }
	  return new Processor(plugins)
	}

	postcss.plugin = function plugin(name, initializer) {
	  let warningPrinted = false;
	  function creator(...args) {
	    // eslint-disable-next-line no-console
	    if (console && console.warn && !warningPrinted) {
	      warningPrinted = true;
	      // eslint-disable-next-line no-console
	      console.warn(
	        name +
	          ': postcss.plugin was deprecated. Migration guide:\n' +
	          'https://evilmartians.com/chronicles/postcss-8-plugin-migration'
	      );
	      if (process.env.LANG && process.env.LANG.startsWith('cn')) {
	        /* c8 ignore next 7 */
	        // eslint-disable-next-line no-console
	        console.warn(
	          name +
	            ': 里面 postcss.plugin 被弃用. 迁移指南:\n' +
	            'https://www.w3ctech.com/topic/2226'
	        );
	      }
	    }
	    let transformer = initializer(...args);
	    transformer.postcssPlugin = name;
	    transformer.postcssVersion = new Processor().version;
	    return transformer
	  }

	  let cache;
	  Object.defineProperty(creator, 'postcss', {
	    get() {
	      if (!cache) cache = creator();
	      return cache
	    }
	  });

	  creator.process = function (css, processOpts, pluginOpts) {
	    return postcss([creator(pluginOpts)]).process(css, processOpts)
	  };

	  return creator
	};

	postcss.stringify = stringify;
	postcss.parse = parse;
	postcss.fromJSON = fromJSON;
	postcss.list = list;

	postcss.comment = defaults => new Comment(defaults);
	postcss.atRule = defaults => new AtRule(defaults);
	postcss.decl = defaults => new Declaration(defaults);
	postcss.rule = defaults => new Rule(defaults);
	postcss.root = defaults => new Root(defaults);
	postcss.document = defaults => new Document(defaults);

	postcss.CssSyntaxError = CssSyntaxError;
	postcss.Declaration = Declaration;
	postcss.Container = Container;
	postcss.Processor = Processor;
	postcss.Document = Document;
	postcss.Comment = Comment;
	postcss.Warning = Warning;
	postcss.AtRule = AtRule;
	postcss.Result = Result;
	postcss.Input = Input;
	postcss.Rule = Rule;
	postcss.Root = Root;
	postcss.Node = Node;

	LazyResult.registerPostcss(postcss);

	postcss_1 = postcss;
	postcss.default = postcss;
	return postcss_1;
}

var postcssExports = requirePostcss();
var postcss = /*@__PURE__*/getDefaultExportFromCjs(postcssExports);

postcss.stringify;
postcss.fromJSON;
postcss.plugin;
postcss.parse;
postcss.list;

postcss.document;
postcss.comment;
postcss.atRule;
postcss.rule;
postcss.decl;
postcss.root;

postcss.CssSyntaxError;
postcss.Declaration;
postcss.Container;
postcss.Processor;
postcss.Document;
postcss.Comment;
postcss.Warning;
postcss.AtRule;
postcss.Result;
postcss.Input;
postcss.Rule;
postcss.Root;
postcss.Node;

function iu(){return {async:!1,breaks:!1,extensions:null,gfm:!0,hooks:null,pedantic:!1,renderer:null,silent:!1,tokenizer:null,walkTokens:null}}let be$1=iu();function Xu(t){be$1=t;}const Qu=/[&<>"']/,Gt=new RegExp(Qu.source,"g"),Wu=/[<>"']|&(?!(#\d{1,7}|#[Xx][a-fA-F0-9]{1,6}|\w+);)/,Zt$1=new RegExp(Wu.source,"g"),Xt$2={"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"},Eu=t=>Xt$2[t];function W(t,e){if(e){if(Qu.test(t))return t.replace(Gt,Eu)}else if(Wu.test(t))return t.replace(Zt$1,Eu);return t}const Qt$1=/&(#(?:\d+)|(?:#x[0-9A-Fa-f]+)|(?:\w+));?/ig;function Wt$1(t){return t.replace(Qt$1,(e,u)=>(u=u.toLowerCase(),u==="colon"?":":u.charAt(0)==="#"?u.charAt(1)==="x"?String.fromCharCode(parseInt(u.substring(2),16)):String.fromCharCode(+u.substring(1)):""))}const Kt$1=/(^|[^\[])\^/g;function R(t,e){let u=typeof t=="string"?t:t.source;e=e||"";const r={replace:(n,a)=>{let i=typeof a=="string"?a:a.source;return i=i.replace(Kt$1,"$1"),u=u.replace(n,i),r},getRegex:()=>new RegExp(u,e)};return r}function wu(t){try{t=encodeURI(t).replace(/%25/g,"%");}catch{return null}return t}const ye={exec:()=>null};function Fu(t,e){const u=t.replace(/\|/g,(a,i,l)=>{let o=!1,d=i;for(;--d>=0&&l[d]==="\\";)o=!o;return o?"|":" |"}),r=u.split(/ \|/);let n=0;if(r[0].trim()||r.shift(),r.length>0&&!r[r.length-1].trim()&&r.pop(),e)if(r.length>e)r.splice(e);else for(;r.length<e;)r.push("");for(;n<r.length;n++)r[n]=r[n].trim().replace(/\\\|/g,"|");return r}function Be$1(t,e,u){const r=t.length;if(r===0)return "";let n=0;for(;n<r;){const a=t.charAt(r-n-1);if(a===e&&!u)n++;else if(a!==e&&u)n++;else break}return t.slice(0,r-n)}function Yt$1(t,e){if(t.indexOf(e[1])===-1)return -1;let u=0;for(let r=0;r<t.length;r++)if(t[r]==="\\")r++;else if(t[r]===e[0])u++;else if(t[r]===e[1]&&(u--,u<0))return r;return -1}function Cu(t,e,u,r){const n=e.href,a=e.title?W(e.title):null,i=t[1].replace(/\\([\[\]])/g,"$1");if(t[0].charAt(0)!=="!"){r.state.inLink=!0;const l={type:"link",raw:u,href:n,title:a,text:i,tokens:r.inlineTokens(i)};return r.state.inLink=!1,l}return {type:"image",raw:u,href:n,title:a,text:W(i)}}function Jt$1(t,e){const u=t.match(/^(\s+)(?:```)/);if(u===null)return e;const r=u[1];return e.split(`
`).map(n=>{const a=n.match(/^\s+/);if(a===null)return n;const[i]=a;return i.length>=r.length?n.slice(r.length):n}).join(`
`)}class Pe{options;rules;lexer;constructor(e){this.options=e||be$1;}space(e){const u=this.rules.block.newline.exec(e);if(u&&u[0].length>0)return {type:"space",raw:u[0]}}code(e){const u=this.rules.block.code.exec(e);if(u){const r=u[0].replace(/^ {1,4}/gm,"");return {type:"code",raw:u[0],codeBlockStyle:"indented",text:this.options.pedantic?r:Be$1(r,`
`)}}}fences(e){const u=this.rules.block.fences.exec(e);if(u){const r=u[0],n=Jt$1(r,u[3]||"");return {type:"code",raw:r,lang:u[2]?u[2].trim().replace(this.rules.inline.anyPunctuation,"$1"):u[2],text:n}}}heading(e){const u=this.rules.block.heading.exec(e);if(u){let r=u[2].trim();if(/#$/.test(r)){const n=Be$1(r,"#");(this.options.pedantic||!n||/ $/.test(n))&&(r=n.trim());}return {type:"heading",raw:u[0],depth:u[1].length,text:r,tokens:this.lexer.inline(r)}}}hr(e){const u=this.rules.block.hr.exec(e);if(u)return {type:"hr",raw:u[0]}}blockquote(e){const u=this.rules.block.blockquote.exec(e);if(u){const r=Be$1(u[0].replace(/^ *>[ \t]?/gm,""),`
`),n=this.lexer.state.top;this.lexer.state.top=!0;const a=this.lexer.blockTokens(r);return this.lexer.state.top=n,{type:"blockquote",raw:u[0],tokens:a,text:r}}}list(e){let u=this.rules.block.list.exec(e);if(u){let r=u[1].trim();const n=r.length>1,a={type:"list",raw:"",ordered:n,start:n?+r.slice(0,-1):"",loose:!1,items:[]};r=n?`\\d{1,9}\\${r.slice(-1)}`:`\\${r}`,this.options.pedantic&&(r=n?r:"[*+-]");const i=new RegExp(`^( {0,3}${r})((?:[	 ][^\\n]*)?(?:\\n|$))`);let l="",o="",d=!1;for(;e;){let f=!1;if(!(u=i.exec(e))||this.rules.block.hr.test(e))break;l=u[0],e=e.substring(l.length);let p=u[2].split(`
`,1)[0].replace(/^\t+/,E=>" ".repeat(3*E.length)),s=e.split(`
`,1)[0],c=0;this.options.pedantic?(c=2,o=p.trimStart()):(c=u[2].search(/[^ ]/),c=c>4?1:c,o=p.slice(c),c+=u[1].length);let x=!1;if(!p&&/^ *$/.test(s)&&(l+=s+`
`,e=e.substring(s.length+1),f=!0),!f){const E=new RegExp(`^ {0,${Math.min(3,c-1)}}(?:[*+-]|\\d{1,9}[.)])((?:[ 	][^\\n]*)?(?:\\n|$))`),C=new RegExp(`^ {0,${Math.min(3,c-1)}}((?:- *){3,}|(?:_ *){3,}|(?:\\* *){3,})(?:\\n+|$)`),F=new RegExp(`^ {0,${Math.min(3,c-1)}}(?:\`\`\`|~~~)`),S=new RegExp(`^ {0,${Math.min(3,c-1)}}#`);for(;e;){const _=e.split(`
`,1)[0];if(s=_,this.options.pedantic&&(s=s.replace(/^ {1,4}(?=( {4})*[^ ])/g,"  ")),F.test(s)||S.test(s)||E.test(s)||C.test(e))break;if(s.search(/[^ ]/)>=c||!s.trim())o+=`
`+s.slice(c);else {if(x||p.search(/[^ ]/)>=4||F.test(p)||S.test(p)||C.test(p))break;o+=`
`+s;}!x&&!s.trim()&&(x=!0),l+=_+`
`,e=e.substring(_.length+1),p=s.slice(c);}}a.loose||(d?a.loose=!0:/\n *\n *$/.test(l)&&(d=!0));let y=null,v;this.options.gfm&&(y=/^\[[ xX]\] /.exec(o),y&&(v=y[0]!=="[ ] ",o=o.replace(/^\[[ xX]\] +/,""))),a.items.push({type:"list_item",raw:l,task:!!y,checked:v,loose:!1,text:o,tokens:[]}),a.raw+=l;}a.items[a.items.length-1].raw=l.trimEnd(),a.items[a.items.length-1].text=o.trimEnd(),a.raw=a.raw.trimEnd();for(let f=0;f<a.items.length;f++)if(this.lexer.state.top=!1,a.items[f].tokens=this.lexer.blockTokens(a.items[f].text,[]),!a.loose){const p=a.items[f].tokens.filter(c=>c.type==="space"),s=p.length>0&&p.some(c=>/\n.*\n/.test(c.raw));a.loose=s;}if(a.loose)for(let f=0;f<a.items.length;f++)a.items[f].loose=!0;return a}}html(e){const u=this.rules.block.html.exec(e);if(u)return {type:"html",block:!0,raw:u[0],pre:u[1]==="pre"||u[1]==="script"||u[1]==="style",text:u[0]}}def(e){const u=this.rules.block.def.exec(e);if(u){const r=u[1].toLowerCase().replace(/\s+/g," "),n=u[2]?u[2].replace(/^<(.*)>$/,"$1").replace(this.rules.inline.anyPunctuation,"$1"):"",a=u[3]?u[3].substring(1,u[3].length-1).replace(this.rules.inline.anyPunctuation,"$1"):u[3];return {type:"def",tag:r,raw:u[0],href:n,title:a}}}table(e){const u=this.rules.block.table.exec(e);if(!u||!/[:|]/.test(u[2]))return;const r=Fu(u[1]),n=u[2].replace(/^\||\| *$/g,"").split("|"),a=u[3]&&u[3].trim()?u[3].replace(/\n[ \t]*$/,"").split(`
`):[],i={type:"table",raw:u[0],header:[],align:[],rows:[]};if(r.length===n.length){for(const l of n)/^ *-+: *$/.test(l)?i.align.push("right"):/^ *:-+: *$/.test(l)?i.align.push("center"):/^ *:-+ *$/.test(l)?i.align.push("left"):i.align.push(null);for(const l of r)i.header.push({text:l,tokens:this.lexer.inline(l)});for(const l of a)i.rows.push(Fu(l,i.header.length).map(o=>({text:o,tokens:this.lexer.inline(o)})));return i}}lheading(e){const u=this.rules.block.lheading.exec(e);if(u)return {type:"heading",raw:u[0],depth:u[2].charAt(0)==="="?1:2,text:u[1],tokens:this.lexer.inline(u[1])}}paragraph(e){const u=this.rules.block.paragraph.exec(e);if(u){const r=u[1].charAt(u[1].length-1)===`
`?u[1].slice(0,-1):u[1];return {type:"paragraph",raw:u[0],text:r,tokens:this.lexer.inline(r)}}}text(e){const u=this.rules.block.text.exec(e);if(u)return {type:"text",raw:u[0],text:u[0],tokens:this.lexer.inline(u[0])}}escape(e){const u=this.rules.inline.escape.exec(e);if(u)return {type:"escape",raw:u[0],text:W(u[1])}}tag(e){const u=this.rules.inline.tag.exec(e);if(u)return !this.lexer.state.inLink&&/^<a /i.test(u[0])?this.lexer.state.inLink=!0:this.lexer.state.inLink&&/^<\/a>/i.test(u[0])&&(this.lexer.state.inLink=!1),!this.lexer.state.inRawBlock&&/^<(pre|code|kbd|script)(\s|>)/i.test(u[0])?this.lexer.state.inRawBlock=!0:this.lexer.state.inRawBlock&&/^<\/(pre|code|kbd|script)(\s|>)/i.test(u[0])&&(this.lexer.state.inRawBlock=!1),{type:"html",raw:u[0],inLink:this.lexer.state.inLink,inRawBlock:this.lexer.state.inRawBlock,block:!1,text:u[0]}}link(e){const u=this.rules.inline.link.exec(e);if(u){const r=u[2].trim();if(!this.options.pedantic&&/^</.test(r)){if(!/>$/.test(r))return;const i=Be$1(r.slice(0,-1),"\\");if((r.length-i.length)%2===0)return}else {const i=Yt$1(u[2],"()");if(i>-1){const o=(u[0].indexOf("!")===0?5:4)+u[1].length+i;u[2]=u[2].substring(0,i),u[0]=u[0].substring(0,o).trim(),u[3]="";}}let n=u[2],a="";if(this.options.pedantic){const i=/^([^'"]*[^\s])\s+(['"])(.*)\2/.exec(n);i&&(n=i[1],a=i[3]);}else a=u[3]?u[3].slice(1,-1):"";return n=n.trim(),/^</.test(n)&&(this.options.pedantic&&!/>$/.test(r)?n=n.slice(1):n=n.slice(1,-1)),Cu(u,{href:n&&n.replace(this.rules.inline.anyPunctuation,"$1"),title:a&&a.replace(this.rules.inline.anyPunctuation,"$1")},u[0],this.lexer)}}reflink(e,u){let r;if((r=this.rules.inline.reflink.exec(e))||(r=this.rules.inline.nolink.exec(e))){const n=(r[2]||r[1]).replace(/\s+/g," "),a=u[n.toLowerCase()];if(!a){const i=r[0].charAt(0);return {type:"text",raw:i,text:i}}return Cu(r,a,r[0],this.lexer)}}emStrong(e,u,r=""){let n=this.rules.inline.emStrongLDelim.exec(e);if(!n||n[3]&&r.match(/[\p{L}\p{N}]/u))return;if(!(n[1]||n[2]||"")||!r||this.rules.inline.punctuation.exec(r)){const i=[...n[0]].length-1;let l,o,d=i,f=0;const p=n[0][0]==="*"?this.rules.inline.emStrongRDelimAst:this.rules.inline.emStrongRDelimUnd;for(p.lastIndex=0,u=u.slice(-1*e.length+i);(n=p.exec(u))!=null;){if(l=n[1]||n[2]||n[3]||n[4]||n[5]||n[6],!l)continue;if(o=[...l].length,n[3]||n[4]){d+=o;continue}else if((n[5]||n[6])&&i%3&&!((i+o)%3)){f+=o;continue}if(d-=o,d>0)continue;o=Math.min(o,o+d+f);const s=[...n[0]][0].length,c=e.slice(0,i+n.index+s+o);if(Math.min(i,o)%2){const y=c.slice(1,-1);return {type:"em",raw:c,text:y,tokens:this.lexer.inlineTokens(y)}}const x=c.slice(2,-2);return {type:"strong",raw:c,text:x,tokens:this.lexer.inlineTokens(x)}}}}codespan(e){const u=this.rules.inline.code.exec(e);if(u){let r=u[2].replace(/\n/g," ");const n=/[^ ]/.test(r),a=/^ /.test(r)&&/ $/.test(r);return n&&a&&(r=r.substring(1,r.length-1)),r=W(r,!0),{type:"codespan",raw:u[0],text:r}}}br(e){const u=this.rules.inline.br.exec(e);if(u)return {type:"br",raw:u[0]}}del(e){const u=this.rules.inline.del.exec(e);if(u)return {type:"del",raw:u[0],text:u[2],tokens:this.lexer.inlineTokens(u[2])}}autolink(e){const u=this.rules.inline.autolink.exec(e);if(u){let r,n;return u[2]==="@"?(r=W(u[1]),n="mailto:"+r):(r=W(u[1]),n=r),{type:"link",raw:u[0],text:r,href:n,tokens:[{type:"text",raw:r,text:r}]}}}url(e){let u;if(u=this.rules.inline.url.exec(e)){let r,n;if(u[2]==="@")r=W(u[0]),n="mailto:"+r;else {let a;do a=u[0],u[0]=this.rules.inline._backpedal.exec(u[0])?.[0]??"";while(a!==u[0]);r=W(u[0]),u[1]==="www."?n="http://"+u[0]:n=u[0];}return {type:"link",raw:u[0],text:r,href:n,tokens:[{type:"text",raw:r,text:r}]}}}inlineText(e){const u=this.rules.inline.text.exec(e);if(u){let r;return this.lexer.state.inRawBlock?r=u[0]:r=W(u[0]),{type:"text",raw:u[0],text:r}}}}const e0=/^(?: *(?:\n|$))+/,u0=/^( {4}[^\n]+(?:\n(?: *(?:\n|$))*)?)+/,t0=/^ {0,3}(`{3,}(?=[^`\n]*(?:\n|$))|~{3,})([^\n]*)(?:\n|$)(?:|([\s\S]*?)(?:\n|$))(?: {0,3}\1[~`]* *(?=\n|$)|$)/,Ce$1=/^ {0,3}((?:-[\t ]*){3,}|(?:_[ \t]*){3,}|(?:\*[ \t]*){3,})(?:\n+|$)/,r0=/^ {0,3}(#{1,6})(?=\s|$)(.*)(?:\n+|$)/,Ku=/(?:[*+-]|\d{1,9}[.)])/,Yu=R(/^(?!bull )((?:.|\n(?!\s*?\n|bull ))+?)\n {0,3}(=+|-+) *(?:\n+|$)/).replace(/bull/g,Ku).getRegex(),su=/^([^\n]+(?:\n(?!hr|heading|lheading|blockquote|fences|list|html|table| +\n)[^\n]+)*)/,n0=/^[^\n]+/,cu=/(?!\s*\])(?:\\.|[^\[\]\\])+/,a0=R(/^ {0,3}\[(label)\]: *(?:\n *)?([^<\s][^\s]*|<.*?>)(?:(?: +(?:\n *)?| *\n *)(title))? *(?:\n+|$)/).replace("label",cu).replace("title",/(?:"(?:\\"?|[^"\\])*"|'[^'\n]*(?:\n[^'\n]+)*\n?'|\([^()]*\))/).getRegex(),i0=R(/^( {0,3}bull)([ \t][^\n]+?)?(?:\n|$)/).replace(/bull/g,Ku).getRegex(),Ve="address|article|aside|base|basefont|blockquote|body|caption|center|col|colgroup|dd|details|dialog|dir|div|dl|dt|fieldset|figcaption|figure|footer|form|frame|frameset|h[1-6]|head|header|hr|html|iframe|legend|li|link|main|menu|menuitem|meta|nav|noframes|ol|optgroup|option|p|param|search|section|summary|table|tbody|td|tfoot|th|thead|title|tr|track|ul",ou=/<!--(?:-?>|[\s\S]*?(?:-->|$))/,s0=R("^ {0,3}(?:<(script|pre|style|textarea)[\\s>][\\s\\S]*?(?:</\\1>[^\\n]*\\n+|$)|comment[^\\n]*(\\n+|$)|<\\?[\\s\\S]*?(?:\\?>\\n*|$)|<![A-Z][\\s\\S]*?(?:>\\n*|$)|<!\\[CDATA\\[[\\s\\S]*?(?:\\]\\]>\\n*|$)|</?(tag)(?: +|\\n|/?>)[\\s\\S]*?(?:(?:\\n *)+\\n|$)|<(?!script|pre|style|textarea)([a-z][\\w-]*)(?:attribute)*? */?>(?=[ \\t]*(?:\\n|$))[\\s\\S]*?(?:(?:\\n *)+\\n|$)|</(?!script|pre|style|textarea)[a-z][\\w-]*\\s*>(?=[ \\t]*(?:\\n|$))[\\s\\S]*?(?:(?:\\n *)+\\n|$))","i").replace("comment",ou).replace("tag",Ve).replace("attribute",/ +[a-zA-Z:_][\w.:-]*(?: *= *"[^"\n]*"| *= *'[^'\n]*'| *= *[^\s"'=<>`]+)?/).getRegex(),Ju=R(su).replace("hr",Ce$1).replace("heading"," {0,3}#{1,6}(?:\\s|$)").replace("|lheading","").replace("|table","").replace("blockquote"," {0,3}>").replace("fences"," {0,3}(?:`{3,}(?=[^`\\n]*\\n)|~{3,})[^\\n]*\\n").replace("list"," {0,3}(?:[*+-]|1[.)]) ").replace("html","</?(?:tag)(?: +|\\n|/?>)|<(?:script|pre|style|textarea|!--)").replace("tag",Ve).getRegex(),c0=R(/^( {0,3}> ?(paragraph|[^\n]*)(?:\n|$))+/).replace("paragraph",Ju).getRegex(),lu={blockquote:c0,code:u0,def:a0,fences:t0,heading:r0,hr:Ce$1,html:s0,lheading:Yu,list:i0,newline:e0,paragraph:Ju,table:ye,text:n0},ku=R("^ *([^\\n ].*)\\n {0,3}((?:\\| *)?:?-+:? *(?:\\| *:?-+:? *)*(?:\\| *)?)(?:\\n((?:(?! *\\n|hr|heading|blockquote|code|fences|list|html).*(?:\\n|$))*)\\n*|$)").replace("hr",Ce$1).replace("heading"," {0,3}#{1,6}(?:\\s|$)").replace("blockquote"," {0,3}>").replace("code"," {4}[^\\n]").replace("fences"," {0,3}(?:`{3,}(?=[^`\\n]*\\n)|~{3,})[^\\n]*\\n").replace("list"," {0,3}(?:[*+-]|1[.)]) ").replace("html","</?(?:tag)(?: +|\\n|/?>)|<(?:script|pre|style|textarea|!--)").replace("tag",Ve).getRegex(),o0={...lu,table:ku,paragraph:R(su).replace("hr",Ce$1).replace("heading"," {0,3}#{1,6}(?:\\s|$)").replace("|lheading","").replace("table",ku).replace("blockquote"," {0,3}>").replace("fences"," {0,3}(?:`{3,}(?=[^`\\n]*\\n)|~{3,})[^\\n]*\\n").replace("list"," {0,3}(?:[*+-]|1[.)]) ").replace("html","</?(?:tag)(?: +|\\n|/?>)|<(?:script|pre|style|textarea|!--)").replace("tag",Ve).getRegex()},l0={...lu,html:R(`^ *(?:comment *(?:\\n|\\s*$)|<(tag)[\\s\\S]+?</\\1> *(?:\\n{2,}|\\s*$)|<tag(?:"[^"]*"|'[^']*'|\\s[^'"/>\\s]*)*?/?> *(?:\\n{2,}|\\s*$))`).replace("comment",ou).replace(/tag/g,"(?!(?:a|em|strong|small|s|cite|q|dfn|abbr|data|time|code|var|samp|kbd|sub|sup|i|b|u|mark|ruby|rt|rp|bdi|bdo|span|br|wbr|ins|del|img)\\b)\\w+(?!:|[^\\w\\s@]*@)\\b").getRegex(),def:/^ *\[([^\]]+)\]: *<?([^\s>]+)>?(?: +(["(][^\n]+[")]))? *(?:\n+|$)/,heading:/^(#{1,6})(.*)(?:\n+|$)/,fences:ye,lheading:/^(.+?)\n {0,3}(=+|-+) *(?:\n+|$)/,paragraph:R(su).replace("hr",Ce$1).replace("heading",` *#{1,6} *[^
]`).replace("lheading",Yu).replace("|table","").replace("blockquote"," {0,3}>").replace("|fences","").replace("|list","").replace("|html","").replace("|tag","").getRegex()},et$2=/^\\([!"#$%&'()*+,\-./:;<=>?@\[\]\\^_`{|}~])/,d0=/^(`+)([^`]|[^`][\s\S]*?[^`])\1(?!`)/,ut=/^( {2,}|\\)\n(?!\s*$)/,f0=/^(`+|[^`])(?:(?= {2,}\n)|[\s\S]*?(?:(?=[\\<!\[`*_]|\b_|$)|[^ ](?= {2,}\n)))/,ke="\\p{P}\\p{S}",h0=R(/^((?![*_])[\spunctuation])/,"u").replace(/punctuation/g,ke).getRegex(),b0=/\[[^[\]]*?\]\([^\(\)]*?\)|`[^`]*?`|<[^<>]*?>/g,p0=R(/^(?:\*+(?:((?!\*)[punct])|[^\s*]))|^_+(?:((?!_)[punct])|([^\s_]))/,"u").replace(/punct/g,ke).getRegex(),g0=R("^[^_*]*?__[^_*]*?\\*[^_*]*?(?=__)|[^*]+(?=[^*])|(?!\\*)[punct](\\*+)(?=[\\s]|$)|[^punct\\s](\\*+)(?!\\*)(?=[punct\\s]|$)|(?!\\*)[punct\\s](\\*+)(?=[^punct\\s])|[\\s](\\*+)(?!\\*)(?=[punct])|(?!\\*)[punct](\\*+)(?!\\*)(?=[punct])|[^punct\\s](\\*+)(?=[^punct\\s])","gu").replace(/punct/g,ke).getRegex(),m0=R("^[^_*]*?\\*\\*[^_*]*?_[^_*]*?(?=\\*\\*)|[^_]+(?=[^_])|(?!_)[punct](_+)(?=[\\s]|$)|[^punct\\s](_+)(?!_)(?=[punct\\s]|$)|(?!_)[punct\\s](_+)(?=[^punct\\s])|[\\s](_+)(?!_)(?=[punct])|(?!_)[punct](_+)(?!_)(?=[punct])","gu").replace(/punct/g,ke).getRegex(),D0=R(/\\([punct])/,"gu").replace(/punct/g,ke).getRegex(),x0=R(/^<(scheme:[^\s\x00-\x1f<>]*|email)>/).replace("scheme",/[a-zA-Z][a-zA-Z0-9+.-]{1,31}/).replace("email",/[a-zA-Z0-9.!#$%&'*+/=?^_`{|}~-]+(@)[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)+(?![-_])/).getRegex(),A0=R(ou).replace("(?:-->|$)","-->").getRegex(),y0=R("^comment|^</[a-zA-Z][\\w:-]*\\s*>|^<[a-zA-Z][\\w-]*(?:attribute)*?\\s*/?>|^<\\?[\\s\\S]*?\\?>|^<![a-zA-Z]+\\s[\\s\\S]*?>|^<!\\[CDATA\\[[\\s\\S]*?\\]\\]>").replace("comment",A0).replace("attribute",/\s+[a-zA-Z:_][\w.:-]*(?:\s*=\s*"[^"]*"|\s*=\s*'[^']*'|\s*=\s*[^\s"'=<>`]+)?/).getRegex(),Me=/(?:\[(?:\\.|[^\[\]\\])*\]|\\.|`[^`]*`|[^\[\]\\`])*?/,v0=R(/^!?\[(label)\]\(\s*(href)(?:\s+(title))?\s*\)/).replace("label",Me).replace("href",/<(?:\\.|[^\n<>\\])+>|[^\s\x00-\x1f]*/).replace("title",/"(?:\\"?|[^"\\])*"|'(?:\\'?|[^'\\])*'|\((?:\\\)?|[^)\\])*\)/).getRegex(),tt$1=R(/^!?\[(label)\]\[(ref)\]/).replace("label",Me).replace("ref",cu).getRegex(),rt$2=R(/^!?\[(ref)\](?:\[\])?/).replace("ref",cu).getRegex(),E0=R("reflink|nolink(?!\\()","g").replace("reflink",tt$1).replace("nolink",rt$2).getRegex(),du={_backpedal:ye,anyPunctuation:D0,autolink:x0,blockSkip:b0,br:ut,code:d0,del:ye,emStrongLDelim:p0,emStrongRDelimAst:g0,emStrongRDelimUnd:m0,escape:et$2,link:v0,nolink:rt$2,punctuation:h0,reflink:tt$1,reflinkSearch:E0,tag:y0,text:f0,url:ye},w0={...du,link:R(/^!?\[(label)\]\((.*?)\)/).replace("label",Me).getRegex(),reflink:R(/^!?\[(label)\]\s*\[([^\]]*)\]/).replace("label",Me).getRegex()},tu={...du,escape:R(et$2).replace("])","~|])").getRegex(),url:R(/^((?:ftp|https?):\/\/|www\.)(?:[a-zA-Z0-9\-]+\.?)+[^\s<]*|^email/,"i").replace("email",/[A-Za-z0-9._+-]+(@)[a-zA-Z0-9-_]+(?:\.[a-zA-Z0-9-_]*[a-zA-Z0-9])+(?![-_])/).getRegex(),_backpedal:/(?:[^?!.,:;*_'"~()&]+|\([^)]*\)|&(?![a-zA-Z0-9]+;$)|[?!.,:;*_'"~)]+(?!$))+/,del:/^(~~?)(?=[^\s~])([\s\S]*?[^\s~])\1(?=[^~]|$)/,text:/^([`~]+|[^`~])(?:(?= {2,}\n)|(?=[a-zA-Z0-9.!#$%&'*+\/=?_`{\|}~-]+@)|[\s\S]*?(?:(?=[\\<!\[`*~_]|\b_|https?:\/\/|ftp:\/\/|www\.|$)|[^ ](?= {2,}\n)|[^a-zA-Z0-9.!#$%&'*+\/=?_`{\|}~-](?=[a-zA-Z0-9.!#$%&'*+\/=?_`{\|}~-]+@)))/},F0={...tu,br:R(ut).replace("{2,}","*").getRegex(),text:R(tu.text).replace("\\b_","\\b_| {2,}\\n").replace(/\{2,\}/g,"*").getRegex()},Ie={normal:lu,gfm:o0,pedantic:l0},xe$1={normal:du,gfm:tu,breaks:F0,pedantic:w0};class ue{tokens;options;state;tokenizer;inlineQueue;constructor(e){this.tokens=[],this.tokens.links=Object.create(null),this.options=e||be$1,this.options.tokenizer=this.options.tokenizer||new Pe,this.tokenizer=this.options.tokenizer,this.tokenizer.options=this.options,this.tokenizer.lexer=this,this.inlineQueue=[],this.state={inLink:!1,inRawBlock:!1,top:!0};const u={block:Ie.normal,inline:xe$1.normal};this.options.pedantic?(u.block=Ie.pedantic,u.inline=xe$1.pedantic):this.options.gfm&&(u.block=Ie.gfm,this.options.breaks?u.inline=xe$1.breaks:u.inline=xe$1.gfm),this.tokenizer.rules=u;}static get rules(){return {block:Ie,inline:xe$1}}static lex(e,u){return new ue(u).lex(e)}static lexInline(e,u){return new ue(u).inlineTokens(e)}lex(e){e=e.replace(/\r\n|\r/g,`
`),this.blockTokens(e,this.tokens);for(let u=0;u<this.inlineQueue.length;u++){const r=this.inlineQueue[u];this.inlineTokens(r.src,r.tokens);}return this.inlineQueue=[],this.tokens}blockTokens(e,u=[]){this.options.pedantic?e=e.replace(/\t/g,"    ").replace(/^ +$/gm,""):e=e.replace(/^( *)(\t+)/gm,(l,o,d)=>o+"    ".repeat(d.length));let r,n,a,i;for(;e;)if(!(this.options.extensions&&this.options.extensions.block&&this.options.extensions.block.some(l=>(r=l.call({lexer:this},e,u))?(e=e.substring(r.raw.length),u.push(r),!0):!1))){if(r=this.tokenizer.space(e)){e=e.substring(r.raw.length),r.raw.length===1&&u.length>0?u[u.length-1].raw+=`
`:u.push(r);continue}if(r=this.tokenizer.code(e)){e=e.substring(r.raw.length),n=u[u.length-1],n&&(n.type==="paragraph"||n.type==="text")?(n.raw+=`
`+r.raw,n.text+=`
`+r.text,this.inlineQueue[this.inlineQueue.length-1].src=n.text):u.push(r);continue}if(r=this.tokenizer.fences(e)){e=e.substring(r.raw.length),u.push(r);continue}if(r=this.tokenizer.heading(e)){e=e.substring(r.raw.length),u.push(r);continue}if(r=this.tokenizer.hr(e)){e=e.substring(r.raw.length),u.push(r);continue}if(r=this.tokenizer.blockquote(e)){e=e.substring(r.raw.length),u.push(r);continue}if(r=this.tokenizer.list(e)){e=e.substring(r.raw.length),u.push(r);continue}if(r=this.tokenizer.html(e)){e=e.substring(r.raw.length),u.push(r);continue}if(r=this.tokenizer.def(e)){e=e.substring(r.raw.length),n=u[u.length-1],n&&(n.type==="paragraph"||n.type==="text")?(n.raw+=`
`+r.raw,n.text+=`
`+r.raw,this.inlineQueue[this.inlineQueue.length-1].src=n.text):this.tokens.links[r.tag]||(this.tokens.links[r.tag]={href:r.href,title:r.title});continue}if(r=this.tokenizer.table(e)){e=e.substring(r.raw.length),u.push(r);continue}if(r=this.tokenizer.lheading(e)){e=e.substring(r.raw.length),u.push(r);continue}if(a=e,this.options.extensions&&this.options.extensions.startBlock){let l=1/0;const o=e.slice(1);let d;this.options.extensions.startBlock.forEach(f=>{d=f.call({lexer:this},o),typeof d=="number"&&d>=0&&(l=Math.min(l,d));}),l<1/0&&l>=0&&(a=e.substring(0,l+1));}if(this.state.top&&(r=this.tokenizer.paragraph(a))){n=u[u.length-1],i&&n.type==="paragraph"?(n.raw+=`
`+r.raw,n.text+=`
`+r.text,this.inlineQueue.pop(),this.inlineQueue[this.inlineQueue.length-1].src=n.text):u.push(r),i=a.length!==e.length,e=e.substring(r.raw.length);continue}if(r=this.tokenizer.text(e)){e=e.substring(r.raw.length),n=u[u.length-1],n&&n.type==="text"?(n.raw+=`
`+r.raw,n.text+=`
`+r.text,this.inlineQueue.pop(),this.inlineQueue[this.inlineQueue.length-1].src=n.text):u.push(r);continue}if(e){const l="Infinite loop on byte: "+e.charCodeAt(0);if(this.options.silent){console.error(l);break}else throw new Error(l)}}return this.state.top=!0,u}inline(e,u=[]){return this.inlineQueue.push({src:e,tokens:u}),u}inlineTokens(e,u=[]){let r,n,a,i=e,l,o,d;if(this.tokens.links){const f=Object.keys(this.tokens.links);if(f.length>0)for(;(l=this.tokenizer.rules.inline.reflinkSearch.exec(i))!=null;)f.includes(l[0].slice(l[0].lastIndexOf("[")+1,-1))&&(i=i.slice(0,l.index)+"["+"a".repeat(l[0].length-2)+"]"+i.slice(this.tokenizer.rules.inline.reflinkSearch.lastIndex));}for(;(l=this.tokenizer.rules.inline.blockSkip.exec(i))!=null;)i=i.slice(0,l.index)+"["+"a".repeat(l[0].length-2)+"]"+i.slice(this.tokenizer.rules.inline.blockSkip.lastIndex);for(;(l=this.tokenizer.rules.inline.anyPunctuation.exec(i))!=null;)i=i.slice(0,l.index)+"++"+i.slice(this.tokenizer.rules.inline.anyPunctuation.lastIndex);for(;e;)if(o||(d=""),o=!1,!(this.options.extensions&&this.options.extensions.inline&&this.options.extensions.inline.some(f=>(r=f.call({lexer:this},e,u))?(e=e.substring(r.raw.length),u.push(r),!0):!1))){if(r=this.tokenizer.escape(e)){e=e.substring(r.raw.length),u.push(r);continue}if(r=this.tokenizer.tag(e)){e=e.substring(r.raw.length),n=u[u.length-1],n&&r.type==="text"&&n.type==="text"?(n.raw+=r.raw,n.text+=r.text):u.push(r);continue}if(r=this.tokenizer.link(e)){e=e.substring(r.raw.length),u.push(r);continue}if(r=this.tokenizer.reflink(e,this.tokens.links)){e=e.substring(r.raw.length),n=u[u.length-1],n&&r.type==="text"&&n.type==="text"?(n.raw+=r.raw,n.text+=r.text):u.push(r);continue}if(r=this.tokenizer.emStrong(e,i,d)){e=e.substring(r.raw.length),u.push(r);continue}if(r=this.tokenizer.codespan(e)){e=e.substring(r.raw.length),u.push(r);continue}if(r=this.tokenizer.br(e)){e=e.substring(r.raw.length),u.push(r);continue}if(r=this.tokenizer.del(e)){e=e.substring(r.raw.length),u.push(r);continue}if(r=this.tokenizer.autolink(e)){e=e.substring(r.raw.length),u.push(r);continue}if(!this.state.inLink&&(r=this.tokenizer.url(e))){e=e.substring(r.raw.length),u.push(r);continue}if(a=e,this.options.extensions&&this.options.extensions.startInline){let f=1/0;const p=e.slice(1);let s;this.options.extensions.startInline.forEach(c=>{s=c.call({lexer:this},p),typeof s=="number"&&s>=0&&(f=Math.min(f,s));}),f<1/0&&f>=0&&(a=e.substring(0,f+1));}if(r=this.tokenizer.inlineText(a)){e=e.substring(r.raw.length),r.raw.slice(-1)!=="_"&&(d=r.raw.slice(-1)),o=!0,n=u[u.length-1],n&&n.type==="text"?(n.raw+=r.raw,n.text+=r.text):u.push(r);continue}if(e){const f="Infinite loop on byte: "+e.charCodeAt(0);if(this.options.silent){console.error(f);break}else throw new Error(f)}}return u}}class He{options;constructor(e){this.options=e||be$1;}code(e,u,r){const n=(u||"").match(/^\S*/)?.[0];return e=e.replace(/\n$/,"")+`
`,n?'<pre><code class="language-'+W(n)+'">'+(r?e:W(e,!0))+`</code></pre>
`:"<pre><code>"+(r?e:W(e,!0))+`</code></pre>
`}blockquote(e){return `<blockquote>
${e}</blockquote>
`}html(e,u){return e}heading(e,u,r){return `<h${u}>${e}</h${u}>
`}hr(){return `<hr>
`}list(e,u,r){const n=u?"ol":"ul",a=u&&r!==1?' start="'+r+'"':"";return "<"+n+a+`>
`+e+"</"+n+`>
`}listitem(e,u,r){return `<li>${e}</li>
`}checkbox(e){return "<input "+(e?'checked="" ':"")+'disabled="" type="checkbox">'}paragraph(e){return `<p>${e}</p>
`}table(e,u){return u&&(u=`<tbody>${u}</tbody>`),`<table>
<thead>
`+e+`</thead>
`+u+`</table>
`}tablerow(e){return `<tr>
${e}</tr>
`}tablecell(e,u){const r=u.header?"th":"td";return (u.align?`<${r} align="${u.align}">`:`<${r}>`)+e+`</${r}>
`}strong(e){return `<strong>${e}</strong>`}em(e){return `<em>${e}</em>`}codespan(e){return `<code>${e}</code>`}br(){return "<br>"}del(e){return `<del>${e}</del>`}link(e,u,r){const n=wu(e);if(n===null)return r;e=n;let a='<a href="'+e+'"';return u&&(a+=' title="'+u+'"'),a+=">"+r+"</a>",a}image(e,u,r){const n=wu(e);if(n===null)return r;e=n;let a=`<img src="${e}" alt="${r}"`;return u&&(a+=` title="${u}"`),a+=">",a}text(e){return e}}class fu{strong(e){return e}em(e){return e}codespan(e){return e}del(e){return e}html(e){return e}text(e){return e}link(e,u,r){return ""+r}image(e,u,r){return ""+r}br(){return ""}}let te$1 = class te{options;renderer;textRenderer;constructor(e){this.options=e||be$1,this.options.renderer=this.options.renderer||new He,this.renderer=this.options.renderer,this.renderer.options=this.options,this.textRenderer=new fu;}static parse(e,u){return new te(u).parse(e)}static parseInline(e,u){return new te(u).parseInline(e)}parse(e,u=!0){let r="";for(let n=0;n<e.length;n++){const a=e[n];if(this.options.extensions&&this.options.extensions.renderers&&this.options.extensions.renderers[a.type]){const i=a,l=this.options.extensions.renderers[i.type].call({parser:this},i);if(l!==!1||!["space","hr","heading","code","table","blockquote","list","html","paragraph","text"].includes(i.type)){r+=l||"";continue}}switch(a.type){case"space":continue;case"hr":{r+=this.renderer.hr();continue}case"heading":{const i=a;r+=this.renderer.heading(this.parseInline(i.tokens),i.depth,Wt$1(this.parseInline(i.tokens,this.textRenderer)));continue}case"code":{const i=a;r+=this.renderer.code(i.text,i.lang,!!i.escaped);continue}case"table":{const i=a;let l="",o="";for(let f=0;f<i.header.length;f++)o+=this.renderer.tablecell(this.parseInline(i.header[f].tokens),{header:!0,align:i.align[f]});l+=this.renderer.tablerow(o);let d="";for(let f=0;f<i.rows.length;f++){const p=i.rows[f];o="";for(let s=0;s<p.length;s++)o+=this.renderer.tablecell(this.parseInline(p[s].tokens),{header:!1,align:i.align[s]});d+=this.renderer.tablerow(o);}r+=this.renderer.table(l,d);continue}case"blockquote":{const i=a,l=this.parse(i.tokens);r+=this.renderer.blockquote(l);continue}case"list":{const i=a,l=i.ordered,o=i.start,d=i.loose;let f="";for(let p=0;p<i.items.length;p++){const s=i.items[p],c=s.checked,x=s.task;let y="";if(s.task){const v=this.renderer.checkbox(!!c);d?s.tokens.length>0&&s.tokens[0].type==="paragraph"?(s.tokens[0].text=v+" "+s.tokens[0].text,s.tokens[0].tokens&&s.tokens[0].tokens.length>0&&s.tokens[0].tokens[0].type==="text"&&(s.tokens[0].tokens[0].text=v+" "+s.tokens[0].tokens[0].text)):s.tokens.unshift({type:"text",text:v+" "}):y+=v+" ";}y+=this.parse(s.tokens,d),f+=this.renderer.listitem(y,x,!!c);}r+=this.renderer.list(f,l,o);continue}case"html":{const i=a;r+=this.renderer.html(i.text,i.block);continue}case"paragraph":{const i=a;r+=this.renderer.paragraph(this.parseInline(i.tokens));continue}case"text":{let i=a,l=i.tokens?this.parseInline(i.tokens):i.text;for(;n+1<e.length&&e[n+1].type==="text";)i=e[++n],l+=`
`+(i.tokens?this.parseInline(i.tokens):i.text);r+=u?this.renderer.paragraph(l):l;continue}default:{const i='Token with "'+a.type+'" type was not found.';if(this.options.silent)return console.error(i),"";throw new Error(i)}}}return r}parseInline(e,u){u=u||this.renderer;let r="";for(let n=0;n<e.length;n++){const a=e[n];if(this.options.extensions&&this.options.extensions.renderers&&this.options.extensions.renderers[a.type]){const i=this.options.extensions.renderers[a.type].call({parser:this},a);if(i!==!1||!["escape","html","link","image","strong","em","codespan","br","del","text"].includes(a.type)){r+=i||"";continue}}switch(a.type){case"escape":{const i=a;r+=u.text(i.text);break}case"html":{const i=a;r+=u.html(i.text);break}case"link":{const i=a;r+=u.link(i.href,i.title,this.parseInline(i.tokens,u));break}case"image":{const i=a;r+=u.image(i.href,i.title,i.text);break}case"strong":{const i=a;r+=u.strong(this.parseInline(i.tokens,u));break}case"em":{const i=a;r+=u.em(this.parseInline(i.tokens,u));break}case"codespan":{const i=a;r+=u.codespan(i.text);break}case"br":{r+=u.br();break}case"del":{const i=a;r+=u.del(this.parseInline(i.tokens,u));break}case"text":{const i=a;r+=u.text(i.text);break}default:{const i='Token with "'+a.type+'" type was not found.';if(this.options.silent)return console.error(i),"";throw new Error(i)}}}return r}};class Oe{options;constructor(e){this.options=e||be$1;}static passThroughHooks=new Set(["preprocess","postprocess","processAllTokens"]);preprocess(e){return e}postprocess(e){return e}processAllTokens(e){return e}}let nt$2 = class nt{defaults=iu();options=this.setOptions;parse=this.#e(ue.lex,te$1.parse);parseInline=this.#e(ue.lexInline,te$1.parseInline);Parser=te$1;Renderer=He;TextRenderer=fu;Lexer=ue;Tokenizer=Pe;Hooks=Oe;constructor(...e){this.use(...e);}walkTokens(e,u){let r=[];for(const n of e)switch(r=r.concat(u.call(this,n)),n.type){case"table":{const a=n;for(const i of a.header)r=r.concat(this.walkTokens(i.tokens,u));for(const i of a.rows)for(const l of i)r=r.concat(this.walkTokens(l.tokens,u));break}case"list":{const a=n;r=r.concat(this.walkTokens(a.items,u));break}default:{const a=n;this.defaults.extensions?.childTokens?.[a.type]?this.defaults.extensions.childTokens[a.type].forEach(i=>{const l=a[i].flat(1/0);r=r.concat(this.walkTokens(l,u));}):a.tokens&&(r=r.concat(this.walkTokens(a.tokens,u)));}}return r}use(...e){const u=this.defaults.extensions||{renderers:{},childTokens:{}};return e.forEach(r=>{const n={...r};if(n.async=this.defaults.async||n.async||!1,r.extensions&&(r.extensions.forEach(a=>{if(!a.name)throw new Error("extension name required");if("renderer"in a){const i=u.renderers[a.name];i?u.renderers[a.name]=function(...l){let o=a.renderer.apply(this,l);return o===!1&&(o=i.apply(this,l)),o}:u.renderers[a.name]=a.renderer;}if("tokenizer"in a){if(!a.level||a.level!=="block"&&a.level!=="inline")throw new Error("extension level must be 'block' or 'inline'");const i=u[a.level];i?i.unshift(a.tokenizer):u[a.level]=[a.tokenizer],a.start&&(a.level==="block"?u.startBlock?u.startBlock.push(a.start):u.startBlock=[a.start]:a.level==="inline"&&(u.startInline?u.startInline.push(a.start):u.startInline=[a.start]));}"childTokens"in a&&a.childTokens&&(u.childTokens[a.name]=a.childTokens);}),n.extensions=u),r.renderer){const a=this.defaults.renderer||new He(this.defaults);for(const i in r.renderer){if(!(i in a))throw new Error(`renderer '${i}' does not exist`);if(i==="options")continue;const l=i,o=r.renderer[l],d=a[l];a[l]=(...f)=>{let p=o.apply(a,f);return p===!1&&(p=d.apply(a,f)),p||""};}n.renderer=a;}if(r.tokenizer){const a=this.defaults.tokenizer||new Pe(this.defaults);for(const i in r.tokenizer){if(!(i in a))throw new Error(`tokenizer '${i}' does not exist`);if(["options","rules","lexer"].includes(i))continue;const l=i,o=r.tokenizer[l],d=a[l];a[l]=(...f)=>{let p=o.apply(a,f);return p===!1&&(p=d.apply(a,f)),p};}n.tokenizer=a;}if(r.hooks){const a=this.defaults.hooks||new Oe;for(const i in r.hooks){if(!(i in a))throw new Error(`hook '${i}' does not exist`);if(i==="options")continue;const l=i,o=r.hooks[l],d=a[l];Oe.passThroughHooks.has(i)?a[l]=f=>{if(this.defaults.async)return Promise.resolve(o.call(a,f)).then(s=>d.call(a,s));const p=o.call(a,f);return d.call(a,p)}:a[l]=(...f)=>{let p=o.apply(a,f);return p===!1&&(p=d.apply(a,f)),p};}n.hooks=a;}if(r.walkTokens){const a=this.defaults.walkTokens,i=r.walkTokens;n.walkTokens=function(l){let o=[];return o.push(i.call(this,l)),a&&(o=o.concat(a.call(this,l))),o};}this.defaults={...this.defaults,...n};}),this}setOptions(e){return this.defaults={...this.defaults,...e},this}lexer(e,u){return ue.lex(e,u??this.defaults)}parser(e,u){return te$1.parse(e,u??this.defaults)}#e(e,u){return (r,n)=>{const a={...n},i={...this.defaults,...a};this.defaults.async===!0&&a.async===!1&&(i.silent||console.warn("marked(): The async option was set to true by an extension. The async: false option sent to parse will be ignored."),i.async=!0);const l=this.#u(!!i.silent,!!i.async);if(typeof r>"u"||r===null)return l(new Error("marked(): input parameter is undefined or null"));if(typeof r!="string")return l(new Error("marked(): input parameter is of type "+Object.prototype.toString.call(r)+", string expected"));if(i.hooks&&(i.hooks.options=i),i.async)return Promise.resolve(i.hooks?i.hooks.preprocess(r):r).then(o=>e(o,i)).then(o=>i.hooks?i.hooks.processAllTokens(o):o).then(o=>i.walkTokens?Promise.all(this.walkTokens(o,i.walkTokens)).then(()=>o):o).then(o=>u(o,i)).then(o=>i.hooks?i.hooks.postprocess(o):o).catch(l);try{i.hooks&&(r=i.hooks.preprocess(r));let o=e(r,i);i.hooks&&(o=i.hooks.processAllTokens(o)),i.walkTokens&&this.walkTokens(o,i.walkTokens);let d=u(o,i);return i.hooks&&(d=i.hooks.postprocess(d)),d}catch(o){return l(o)}}}#u(e,u){return r=>{if(r.message+=`
Please report this to https://github.com/markedjs/marked.`,e){const n="<p>An error occurred:</p><pre>"+W(r.message+"",!0)+"</pre>";return u?Promise.resolve(n):n}if(u)return Promise.reject(r);throw r}}};const fe$1=new nt$2;function q(t,e){return fe$1.parse(t,e)}q.options=q.setOptions=function(t){return fe$1.setOptions(t),q.defaults=fe$1.defaults,Xu(q.defaults),q};q.getDefaults=iu;q.defaults=be$1;q.use=function(...t){return fe$1.use(...t),q.defaults=fe$1.defaults,Xu(q.defaults),q};q.walkTokens=function(t,e){return fe$1.walkTokens(t,e)};q.parseInline=fe$1.parseInline;q.Parser=te$1;q.parser=te$1.parse;q.Renderer=He;q.TextRenderer=fu;q.Lexer=ue;q.lexer=ue.lex;q.Tokenizer=Pe;q.Hooks=Oe;q.parse=q;q.options;q.setOptions;q.use;q.walkTokens;q.parseInline;te$1.parse;ue.lex;function C0(t){if(typeof t=="function"&&(t={highlight:t}),!t||typeof t.highlight!="function")throw new Error("Must provide highlight function");return typeof t.langPrefix!="string"&&(t.langPrefix="language-"),typeof t.emptyLangClass!="string"&&(t.emptyLangClass=""),{async:!!t.async,walkTokens(e){if(e.type!=="code")return;const u=Tu(e.lang);if(t.async)return Promise.resolve(t.highlight(e.text,u,e.lang||"")).then(Su(e));const r=t.highlight(e.text,u,e.lang||"");if(r instanceof Promise)throw new Error("markedHighlight is not set to async but the highlight function is async. Set the async option to true on markedHighlight to await the async highlight function.");Su(e)(r);},useNewRenderer:!0,renderer:{code(e,u,r){typeof e=="object"&&(r=e.escaped,u=e.lang,e=e.text);const n=Tu(u),a=n?t.langPrefix+Bu(n):t.emptyLangClass,i=a?` class="${a}"`:"";return e=e.replace(/\n$/,""),`<pre><code${i}>${r?e:Bu(e,!0)}
</code></pre>`}}}}function Tu(t){return (t||"").match(/\S*/)[0]}function Su(t){return e=>{typeof e=="string"&&e!==t.text&&(t.escaped=!0,t.text=e);}}const at$2=/[&<>"']/,k0=new RegExp(at$2.source,"g"),it$3=/[<>"']|&(?!(#\d{1,7}|#[Xx][a-fA-F0-9]{1,6}|\w+);)/,T0=new RegExp(it$3.source,"g"),S0={"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"},_u=t=>S0[t];function Bu(t,e){if(e){if(at$2.test(t))return t.replace(k0,_u)}else if(it$3.test(t))return t.replace(T0,_u);return t}const _0=/[\0-\x1F!-,\.\/:-@\[-\^`\{-\xA9\xAB-\xB4\xB6-\xB9\xBB-\xBF\xD7\xF7\u02C2-\u02C5\u02D2-\u02DF\u02E5-\u02EB\u02ED\u02EF-\u02FF\u0375\u0378\u0379\u037E\u0380-\u0385\u0387\u038B\u038D\u03A2\u03F6\u0482\u0530\u0557\u0558\u055A-\u055F\u0589-\u0590\u05BE\u05C0\u05C3\u05C6\u05C8-\u05CF\u05EB-\u05EE\u05F3-\u060F\u061B-\u061F\u066A-\u066D\u06D4\u06DD\u06DE\u06E9\u06FD\u06FE\u0700-\u070F\u074B\u074C\u07B2-\u07BF\u07F6-\u07F9\u07FB\u07FC\u07FE\u07FF\u082E-\u083F\u085C-\u085F\u086B-\u089F\u08B5\u08C8-\u08D2\u08E2\u0964\u0965\u0970\u0984\u098D\u098E\u0991\u0992\u09A9\u09B1\u09B3-\u09B5\u09BA\u09BB\u09C5\u09C6\u09C9\u09CA\u09CF-\u09D6\u09D8-\u09DB\u09DE\u09E4\u09E5\u09F2-\u09FB\u09FD\u09FF\u0A00\u0A04\u0A0B-\u0A0E\u0A11\u0A12\u0A29\u0A31\u0A34\u0A37\u0A3A\u0A3B\u0A3D\u0A43-\u0A46\u0A49\u0A4A\u0A4E-\u0A50\u0A52-\u0A58\u0A5D\u0A5F-\u0A65\u0A76-\u0A80\u0A84\u0A8E\u0A92\u0AA9\u0AB1\u0AB4\u0ABA\u0ABB\u0AC6\u0ACA\u0ACE\u0ACF\u0AD1-\u0ADF\u0AE4\u0AE5\u0AF0-\u0AF8\u0B00\u0B04\u0B0D\u0B0E\u0B11\u0B12\u0B29\u0B31\u0B34\u0B3A\u0B3B\u0B45\u0B46\u0B49\u0B4A\u0B4E-\u0B54\u0B58-\u0B5B\u0B5E\u0B64\u0B65\u0B70\u0B72-\u0B81\u0B84\u0B8B-\u0B8D\u0B91\u0B96-\u0B98\u0B9B\u0B9D\u0BA0-\u0BA2\u0BA5-\u0BA7\u0BAB-\u0BAD\u0BBA-\u0BBD\u0BC3-\u0BC5\u0BC9\u0BCE\u0BCF\u0BD1-\u0BD6\u0BD8-\u0BE5\u0BF0-\u0BFF\u0C0D\u0C11\u0C29\u0C3A-\u0C3C\u0C45\u0C49\u0C4E-\u0C54\u0C57\u0C5B-\u0C5F\u0C64\u0C65\u0C70-\u0C7F\u0C84\u0C8D\u0C91\u0CA9\u0CB4\u0CBA\u0CBB\u0CC5\u0CC9\u0CCE-\u0CD4\u0CD7-\u0CDD\u0CDF\u0CE4\u0CE5\u0CF0\u0CF3-\u0CFF\u0D0D\u0D11\u0D45\u0D49\u0D4F-\u0D53\u0D58-\u0D5E\u0D64\u0D65\u0D70-\u0D79\u0D80\u0D84\u0D97-\u0D99\u0DB2\u0DBC\u0DBE\u0DBF\u0DC7-\u0DC9\u0DCB-\u0DCE\u0DD5\u0DD7\u0DE0-\u0DE5\u0DF0\u0DF1\u0DF4-\u0E00\u0E3B-\u0E3F\u0E4F\u0E5A-\u0E80\u0E83\u0E85\u0E8B\u0EA4\u0EA6\u0EBE\u0EBF\u0EC5\u0EC7\u0ECE\u0ECF\u0EDA\u0EDB\u0EE0-\u0EFF\u0F01-\u0F17\u0F1A-\u0F1F\u0F2A-\u0F34\u0F36\u0F38\u0F3A-\u0F3D\u0F48\u0F6D-\u0F70\u0F85\u0F98\u0FBD-\u0FC5\u0FC7-\u0FFF\u104A-\u104F\u109E\u109F\u10C6\u10C8-\u10CC\u10CE\u10CF\u10FB\u1249\u124E\u124F\u1257\u1259\u125E\u125F\u1289\u128E\u128F\u12B1\u12B6\u12B7\u12BF\u12C1\u12C6\u12C7\u12D7\u1311\u1316\u1317\u135B\u135C\u1360-\u137F\u1390-\u139F\u13F6\u13F7\u13FE-\u1400\u166D\u166E\u1680\u169B-\u169F\u16EB-\u16ED\u16F9-\u16FF\u170D\u1715-\u171F\u1735-\u173F\u1754-\u175F\u176D\u1771\u1774-\u177F\u17D4-\u17D6\u17D8-\u17DB\u17DE\u17DF\u17EA-\u180A\u180E\u180F\u181A-\u181F\u1879-\u187F\u18AB-\u18AF\u18F6-\u18FF\u191F\u192C-\u192F\u193C-\u1945\u196E\u196F\u1975-\u197F\u19AC-\u19AF\u19CA-\u19CF\u19DA-\u19FF\u1A1C-\u1A1F\u1A5F\u1A7D\u1A7E\u1A8A-\u1A8F\u1A9A-\u1AA6\u1AA8-\u1AAF\u1AC1-\u1AFF\u1B4C-\u1B4F\u1B5A-\u1B6A\u1B74-\u1B7F\u1BF4-\u1BFF\u1C38-\u1C3F\u1C4A-\u1C4C\u1C7E\u1C7F\u1C89-\u1C8F\u1CBB\u1CBC\u1CC0-\u1CCF\u1CD3\u1CFB-\u1CFF\u1DFA\u1F16\u1F17\u1F1E\u1F1F\u1F46\u1F47\u1F4E\u1F4F\u1F58\u1F5A\u1F5C\u1F5E\u1F7E\u1F7F\u1FB5\u1FBD\u1FBF-\u1FC1\u1FC5\u1FCD-\u1FCF\u1FD4\u1FD5\u1FDC-\u1FDF\u1FED-\u1FF1\u1FF5\u1FFD-\u203E\u2041-\u2053\u2055-\u2070\u2072-\u207E\u2080-\u208F\u209D-\u20CF\u20F1-\u2101\u2103-\u2106\u2108\u2109\u2114\u2116-\u2118\u211E-\u2123\u2125\u2127\u2129\u212E\u213A\u213B\u2140-\u2144\u214A-\u214D\u214F-\u215F\u2189-\u24B5\u24EA-\u2BFF\u2C2F\u2C5F\u2CE5-\u2CEA\u2CF4-\u2CFF\u2D26\u2D28-\u2D2C\u2D2E\u2D2F\u2D68-\u2D6E\u2D70-\u2D7E\u2D97-\u2D9F\u2DA7\u2DAF\u2DB7\u2DBF\u2DC7\u2DCF\u2DD7\u2DDF\u2E00-\u2E2E\u2E30-\u3004\u3008-\u3020\u3030\u3036\u3037\u303D-\u3040\u3097\u3098\u309B\u309C\u30A0\u30FB\u3100-\u3104\u3130\u318F-\u319F\u31C0-\u31EF\u3200-\u33FF\u4DC0-\u4DFF\u9FFD-\u9FFF\uA48D-\uA4CF\uA4FE\uA4FF\uA60D-\uA60F\uA62C-\uA63F\uA673\uA67E\uA6F2-\uA716\uA720\uA721\uA789\uA78A\uA7C0\uA7C1\uA7CB-\uA7F4\uA828-\uA82B\uA82D-\uA83F\uA874-\uA87F\uA8C6-\uA8CF\uA8DA-\uA8DF\uA8F8-\uA8FA\uA8FC\uA92E\uA92F\uA954-\uA95F\uA97D-\uA97F\uA9C1-\uA9CE\uA9DA-\uA9DF\uA9FF\uAA37-\uAA3F\uAA4E\uAA4F\uAA5A-\uAA5F\uAA77-\uAA79\uAAC3-\uAADA\uAADE\uAADF\uAAF0\uAAF1\uAAF7-\uAB00\uAB07\uAB08\uAB0F\uAB10\uAB17-\uAB1F\uAB27\uAB2F\uAB5B\uAB6A-\uAB6F\uABEB\uABEE\uABEF\uABFA-\uABFF\uD7A4-\uD7AF\uD7C7-\uD7CA\uD7FC-\uD7FF\uE000-\uF8FF\uFA6E\uFA6F\uFADA-\uFAFF\uFB07-\uFB12\uFB18-\uFB1C\uFB29\uFB37\uFB3D\uFB3F\uFB42\uFB45\uFBB2-\uFBD2\uFD3E-\uFD4F\uFD90\uFD91\uFDC8-\uFDEF\uFDFC-\uFDFF\uFE10-\uFE1F\uFE30-\uFE32\uFE35-\uFE4C\uFE50-\uFE6F\uFE75\uFEFD-\uFF0F\uFF1A-\uFF20\uFF3B-\uFF3E\uFF40\uFF5B-\uFF65\uFFBF-\uFFC1\uFFC8\uFFC9\uFFD0\uFFD1\uFFD8\uFFD9\uFFDD-\uFFFF]|\uD800[\uDC0C\uDC27\uDC3B\uDC3E\uDC4E\uDC4F\uDC5E-\uDC7F\uDCFB-\uDD3F\uDD75-\uDDFC\uDDFE-\uDE7F\uDE9D-\uDE9F\uDED1-\uDEDF\uDEE1-\uDEFF\uDF20-\uDF2C\uDF4B-\uDF4F\uDF7B-\uDF7F\uDF9E\uDF9F\uDFC4-\uDFC7\uDFD0\uDFD6-\uDFFF]|\uD801[\uDC9E\uDC9F\uDCAA-\uDCAF\uDCD4-\uDCD7\uDCFC-\uDCFF\uDD28-\uDD2F\uDD64-\uDDFF\uDF37-\uDF3F\uDF56-\uDF5F\uDF68-\uDFFF]|\uD802[\uDC06\uDC07\uDC09\uDC36\uDC39-\uDC3B\uDC3D\uDC3E\uDC56-\uDC5F\uDC77-\uDC7F\uDC9F-\uDCDF\uDCF3\uDCF6-\uDCFF\uDD16-\uDD1F\uDD3A-\uDD7F\uDDB8-\uDDBD\uDDC0-\uDDFF\uDE04\uDE07-\uDE0B\uDE14\uDE18\uDE36\uDE37\uDE3B-\uDE3E\uDE40-\uDE5F\uDE7D-\uDE7F\uDE9D-\uDEBF\uDEC8\uDEE7-\uDEFF\uDF36-\uDF3F\uDF56-\uDF5F\uDF73-\uDF7F\uDF92-\uDFFF]|\uD803[\uDC49-\uDC7F\uDCB3-\uDCBF\uDCF3-\uDCFF\uDD28-\uDD2F\uDD3A-\uDE7F\uDEAA\uDEAD-\uDEAF\uDEB2-\uDEFF\uDF1D-\uDF26\uDF28-\uDF2F\uDF51-\uDFAF\uDFC5-\uDFDF\uDFF7-\uDFFF]|\uD804[\uDC47-\uDC65\uDC70-\uDC7E\uDCBB-\uDCCF\uDCE9-\uDCEF\uDCFA-\uDCFF\uDD35\uDD40-\uDD43\uDD48-\uDD4F\uDD74\uDD75\uDD77-\uDD7F\uDDC5-\uDDC8\uDDCD\uDDDB\uDDDD-\uDDFF\uDE12\uDE38-\uDE3D\uDE3F-\uDE7F\uDE87\uDE89\uDE8E\uDE9E\uDEA9-\uDEAF\uDEEB-\uDEEF\uDEFA-\uDEFF\uDF04\uDF0D\uDF0E\uDF11\uDF12\uDF29\uDF31\uDF34\uDF3A\uDF45\uDF46\uDF49\uDF4A\uDF4E\uDF4F\uDF51-\uDF56\uDF58-\uDF5C\uDF64\uDF65\uDF6D-\uDF6F\uDF75-\uDFFF]|\uD805[\uDC4B-\uDC4F\uDC5A-\uDC5D\uDC62-\uDC7F\uDCC6\uDCC8-\uDCCF\uDCDA-\uDD7F\uDDB6\uDDB7\uDDC1-\uDDD7\uDDDE-\uDDFF\uDE41-\uDE43\uDE45-\uDE4F\uDE5A-\uDE7F\uDEB9-\uDEBF\uDECA-\uDEFF\uDF1B\uDF1C\uDF2C-\uDF2F\uDF3A-\uDFFF]|\uD806[\uDC3B-\uDC9F\uDCEA-\uDCFE\uDD07\uDD08\uDD0A\uDD0B\uDD14\uDD17\uDD36\uDD39\uDD3A\uDD44-\uDD4F\uDD5A-\uDD9F\uDDA8\uDDA9\uDDD8\uDDD9\uDDE2\uDDE5-\uDDFF\uDE3F-\uDE46\uDE48-\uDE4F\uDE9A-\uDE9C\uDE9E-\uDEBF\uDEF9-\uDFFF]|\uD807[\uDC09\uDC37\uDC41-\uDC4F\uDC5A-\uDC71\uDC90\uDC91\uDCA8\uDCB7-\uDCFF\uDD07\uDD0A\uDD37-\uDD39\uDD3B\uDD3E\uDD48-\uDD4F\uDD5A-\uDD5F\uDD66\uDD69\uDD8F\uDD92\uDD99-\uDD9F\uDDAA-\uDEDF\uDEF7-\uDFAF\uDFB1-\uDFFF]|\uD808[\uDF9A-\uDFFF]|\uD809[\uDC6F-\uDC7F\uDD44-\uDFFF]|[\uD80A\uD80B\uD80E-\uD810\uD812-\uD819\uD824-\uD82B\uD82D\uD82E\uD830-\uD833\uD837\uD839\uD83D\uD83F\uD87B-\uD87D\uD87F\uD885-\uDB3F\uDB41-\uDBFF][\uDC00-\uDFFF]|\uD80D[\uDC2F-\uDFFF]|\uD811[\uDE47-\uDFFF]|\uD81A[\uDE39-\uDE3F\uDE5F\uDE6A-\uDECF\uDEEE\uDEEF\uDEF5-\uDEFF\uDF37-\uDF3F\uDF44-\uDF4F\uDF5A-\uDF62\uDF78-\uDF7C\uDF90-\uDFFF]|\uD81B[\uDC00-\uDE3F\uDE80-\uDEFF\uDF4B-\uDF4E\uDF88-\uDF8E\uDFA0-\uDFDF\uDFE2\uDFE5-\uDFEF\uDFF2-\uDFFF]|\uD821[\uDFF8-\uDFFF]|\uD823[\uDCD6-\uDCFF\uDD09-\uDFFF]|\uD82C[\uDD1F-\uDD4F\uDD53-\uDD63\uDD68-\uDD6F\uDEFC-\uDFFF]|\uD82F[\uDC6B-\uDC6F\uDC7D-\uDC7F\uDC89-\uDC8F\uDC9A-\uDC9C\uDC9F-\uDFFF]|\uD834[\uDC00-\uDD64\uDD6A-\uDD6C\uDD73-\uDD7A\uDD83\uDD84\uDD8C-\uDDA9\uDDAE-\uDE41\uDE45-\uDFFF]|\uD835[\uDC55\uDC9D\uDCA0\uDCA1\uDCA3\uDCA4\uDCA7\uDCA8\uDCAD\uDCBA\uDCBC\uDCC4\uDD06\uDD0B\uDD0C\uDD15\uDD1D\uDD3A\uDD3F\uDD45\uDD47-\uDD49\uDD51\uDEA6\uDEA7\uDEC1\uDEDB\uDEFB\uDF15\uDF35\uDF4F\uDF6F\uDF89\uDFA9\uDFC3\uDFCC\uDFCD]|\uD836[\uDC00-\uDDFF\uDE37-\uDE3A\uDE6D-\uDE74\uDE76-\uDE83\uDE85-\uDE9A\uDEA0\uDEB0-\uDFFF]|\uD838[\uDC07\uDC19\uDC1A\uDC22\uDC25\uDC2B-\uDCFF\uDD2D-\uDD2F\uDD3E\uDD3F\uDD4A-\uDD4D\uDD4F-\uDEBF\uDEFA-\uDFFF]|\uD83A[\uDCC5-\uDCCF\uDCD7-\uDCFF\uDD4C-\uDD4F\uDD5A-\uDFFF]|\uD83B[\uDC00-\uDDFF\uDE04\uDE20\uDE23\uDE25\uDE26\uDE28\uDE33\uDE38\uDE3A\uDE3C-\uDE41\uDE43-\uDE46\uDE48\uDE4A\uDE4C\uDE50\uDE53\uDE55\uDE56\uDE58\uDE5A\uDE5C\uDE5E\uDE60\uDE63\uDE65\uDE66\uDE6B\uDE73\uDE78\uDE7D\uDE7F\uDE8A\uDE9C-\uDEA0\uDEA4\uDEAA\uDEBC-\uDFFF]|\uD83C[\uDC00-\uDD2F\uDD4A-\uDD4F\uDD6A-\uDD6F\uDD8A-\uDFFF]|\uD83E[\uDC00-\uDFEF\uDFFA-\uDFFF]|\uD869[\uDEDE-\uDEFF]|\uD86D[\uDF35-\uDF3F]|\uD86E[\uDC1E\uDC1F]|\uD873[\uDEA2-\uDEAF]|\uD87A[\uDFE1-\uDFFF]|\uD87E[\uDE1E-\uDFFF]|\uD884[\uDF4B-\uDFFF]|\uDB40[\uDC00-\uDCFF\uDDF0-\uDFFF]/g,B0=Object.hasOwnProperty;class hu{constructor(){this.occurrences,this.reset();}slug(e,u){const r=this;let n=I0(e,u===!0);const a=n;for(;B0.call(r.occurrences,n);)r.occurrences[a]++,n=a+"-"+r.occurrences[a];return r.occurrences[n]=0,n}reset(){this.occurrences=Object.create(null);}}function I0(t,e){return typeof t!="string"?"":(e||(t=t.toLowerCase()),t.replace(_0,"").replace(/ /g,"-"))}let st$2=new hu,ct$2=[];function N0({prefix:t="",globalSlugs:e=!1}={}){return {headerIds:!1,hooks:{preprocess(u){return e||L0(),u}},renderer:{heading(u,r,n){n=n.toLowerCase().trim().replace(/<[!\/a-z].*?>/gi,"");const a=`${t}${st$2.slug(n)}`,i={level:r,text:u,id:a};return ct$2.push(i),`<h${r} id="${a}">${u}</h${r}>
`}}}}function L0(){ct$2=[],st$2=new hu;}(function(t){var e=/\\(?:[^a-z()[\]]|[a-z*]+)/i,u={"equation-command":{pattern:e,alias:"regex"}};t.languages.latex={comment:/%.*/,cdata:{pattern:/(\\begin\{((?:lstlisting|verbatim)\*?)\})[\s\S]*?(?=\\end\{\2\})/,lookbehind:!0},equation:[{pattern:/\$\$(?:\\[\s\S]|[^\\$])+\$\$|\$(?:\\[\s\S]|[^\\$])+\$|\\\([\s\S]*?\\\)|\\\[[\s\S]*?\\\]/,inside:u,alias:"string"},{pattern:/(\\begin\{((?:align|eqnarray|equation|gather|math|multline)\*?)\})[\s\S]*?(?=\\end\{\2\})/,lookbehind:!0,inside:u,alias:"string"}],keyword:{pattern:/(\\(?:begin|cite|documentclass|end|label|ref|usepackage)(?:\[[^\]]+\])?\{)[^}]+(?=\})/,lookbehind:!0},url:{pattern:/(\\url\{)[^}]+(?=\})/,lookbehind:!0},headline:{pattern:/(\\(?:chapter|frametitle|paragraph|part|section|subparagraph|subsection|subsubparagraph|subsubsection|subsubsubparagraph)\*?(?:\[[^\]]+\])?\{)[^}]+(?=\})/,lookbehind:!0,alias:"class-name"},function:{pattern:e,alias:"selector"},punctuation:/[[\]{}&]/},t.languages.tex=t.languages.latex,t.languages.context=t.languages.latex;})(Prism);(function(t){var e="\\b(?:BASH|BASHOPTS|BASH_ALIASES|BASH_ARGC|BASH_ARGV|BASH_CMDS|BASH_COMPLETION_COMPAT_DIR|BASH_LINENO|BASH_REMATCH|BASH_SOURCE|BASH_VERSINFO|BASH_VERSION|COLORTERM|COLUMNS|COMP_WORDBREAKS|DBUS_SESSION_BUS_ADDRESS|DEFAULTS_PATH|DESKTOP_SESSION|DIRSTACK|DISPLAY|EUID|GDMSESSION|GDM_LANG|GNOME_KEYRING_CONTROL|GNOME_KEYRING_PID|GPG_AGENT_INFO|GROUPS|HISTCONTROL|HISTFILE|HISTFILESIZE|HISTSIZE|HOME|HOSTNAME|HOSTTYPE|IFS|INSTANCE|JOB|LANG|LANGUAGE|LC_ADDRESS|LC_ALL|LC_IDENTIFICATION|LC_MEASUREMENT|LC_MONETARY|LC_NAME|LC_NUMERIC|LC_PAPER|LC_TELEPHONE|LC_TIME|LESSCLOSE|LESSOPEN|LINES|LOGNAME|LS_COLORS|MACHTYPE|MAILCHECK|MANDATORY_PATH|NO_AT_BRIDGE|OLDPWD|OPTERR|OPTIND|ORBIT_SOCKETDIR|OSTYPE|PAPERSIZE|PATH|PIPESTATUS|PPID|PS1|PS2|PS3|PS4|PWD|RANDOM|REPLY|SECONDS|SELINUX_INIT|SESSION|SESSIONTYPE|SESSION_MANAGER|SHELL|SHELLOPTS|SHLVL|SSH_AUTH_SOCK|TERM|UID|UPSTART_EVENTS|UPSTART_INSTANCE|UPSTART_JOB|UPSTART_SESSION|USER|WINDOWID|XAUTHORITY|XDG_CONFIG_DIRS|XDG_CURRENT_DESKTOP|XDG_DATA_DIRS|XDG_GREETER_DATA_DIR|XDG_MENU_PREFIX|XDG_RUNTIME_DIR|XDG_SEAT|XDG_SEAT_PATH|XDG_SESSION_DESKTOP|XDG_SESSION_ID|XDG_SESSION_PATH|XDG_SESSION_TYPE|XDG_VTNR|XMODIFIERS)\\b",u={pattern:/(^(["']?)\w+\2)[ \t]+\S.*/,lookbehind:!0,alias:"punctuation",inside:null},r={bash:u,environment:{pattern:RegExp("\\$"+e),alias:"constant"},variable:[{pattern:/\$?\(\([\s\S]+?\)\)/,greedy:!0,inside:{variable:[{pattern:/(^\$\(\([\s\S]+)\)\)/,lookbehind:!0},/^\$\(\(/],number:/\b0x[\dA-Fa-f]+\b|(?:\b\d+(?:\.\d*)?|\B\.\d+)(?:[Ee]-?\d+)?/,operator:/--|\+\+|\*\*=?|<<=?|>>=?|&&|\|\||[=!+\-*/%<>^&|]=?|[?~:]/,punctuation:/\(\(?|\)\)?|,|;/}},{pattern:/\$\((?:\([^)]+\)|[^()])+\)|`[^`]+`/,greedy:!0,inside:{variable:/^\$\(|^`|\)$|`$/}},{pattern:/\$\{[^}]+\}/,greedy:!0,inside:{operator:/:[-=?+]?|[!\/]|##?|%%?|\^\^?|,,?/,punctuation:/[\[\]]/,environment:{pattern:RegExp("(\\{)"+e),lookbehind:!0,alias:"constant"}}},/\$(?:\w+|[#?*!@$])/],entity:/\\(?:[abceEfnrtv\\"]|O?[0-7]{1,3}|U[0-9a-fA-F]{8}|u[0-9a-fA-F]{4}|x[0-9a-fA-F]{1,2})/};t.languages.bash={shebang:{pattern:/^#!\s*\/.*/,alias:"important"},comment:{pattern:/(^|[^"{\\$])#.*/,lookbehind:!0},"function-name":[{pattern:/(\bfunction\s+)[\w-]+(?=(?:\s*\(?:\s*\))?\s*\{)/,lookbehind:!0,alias:"function"},{pattern:/\b[\w-]+(?=\s*\(\s*\)\s*\{)/,alias:"function"}],"for-or-select":{pattern:/(\b(?:for|select)\s+)\w+(?=\s+in\s)/,alias:"variable",lookbehind:!0},"assign-left":{pattern:/(^|[\s;|&]|[<>]\()\w+(?:\.\w+)*(?=\+?=)/,inside:{environment:{pattern:RegExp("(^|[\\s;|&]|[<>]\\()"+e),lookbehind:!0,alias:"constant"}},alias:"variable",lookbehind:!0},parameter:{pattern:/(^|\s)-{1,2}(?:\w+:[+-]?)?\w+(?:\.\w+)*(?=[=\s]|$)/,alias:"variable",lookbehind:!0},string:[{pattern:/((?:^|[^<])<<-?\s*)(\w+)\s[\s\S]*?(?:\r?\n|\r)\2/,lookbehind:!0,greedy:!0,inside:r},{pattern:/((?:^|[^<])<<-?\s*)(["'])(\w+)\2\s[\s\S]*?(?:\r?\n|\r)\3/,lookbehind:!0,greedy:!0,inside:{bash:u}},{pattern:/(^|[^\\](?:\\\\)*)"(?:\\[\s\S]|\$\([^)]+\)|\$(?!\()|`[^`]+`|[^"\\`$])*"/,lookbehind:!0,greedy:!0,inside:r},{pattern:/(^|[^$\\])'[^']*'/,lookbehind:!0,greedy:!0},{pattern:/\$'(?:[^'\\]|\\[\s\S])*'/,greedy:!0,inside:{entity:r.entity}}],environment:{pattern:RegExp("\\$?"+e),alias:"constant"},variable:r.variable,function:{pattern:/(^|[\s;|&]|[<>]\()(?:add|apropos|apt|apt-cache|apt-get|aptitude|aspell|automysqlbackup|awk|basename|bash|bc|bconsole|bg|bzip2|cal|cargo|cat|cfdisk|chgrp|chkconfig|chmod|chown|chroot|cksum|clear|cmp|column|comm|composer|cp|cron|crontab|csplit|curl|cut|date|dc|dd|ddrescue|debootstrap|df|diff|diff3|dig|dir|dircolors|dirname|dirs|dmesg|docker|docker-compose|du|egrep|eject|env|ethtool|expand|expect|expr|fdformat|fdisk|fg|fgrep|file|find|fmt|fold|format|free|fsck|ftp|fuser|gawk|git|gparted|grep|groupadd|groupdel|groupmod|groups|grub-mkconfig|gzip|halt|head|hg|history|host|hostname|htop|iconv|id|ifconfig|ifdown|ifup|import|install|ip|java|jobs|join|kill|killall|less|link|ln|locate|logname|logrotate|look|lpc|lpr|lprint|lprintd|lprintq|lprm|ls|lsof|lynx|make|man|mc|mdadm|mkconfig|mkdir|mke2fs|mkfifo|mkfs|mkisofs|mknod|mkswap|mmv|more|most|mount|mtools|mtr|mutt|mv|nano|nc|netstat|nice|nl|node|nohup|notify-send|npm|nslookup|op|open|parted|passwd|paste|pathchk|ping|pkill|pnpm|podman|podman-compose|popd|pr|printcap|printenv|ps|pushd|pv|quota|quotacheck|quotactl|ram|rar|rcp|reboot|remsync|rename|renice|rev|rm|rmdir|rpm|rsync|scp|screen|sdiff|sed|sendmail|seq|service|sftp|sh|shellcheck|shuf|shutdown|sleep|slocate|sort|split|ssh|stat|strace|su|sudo|sum|suspend|swapon|sync|sysctl|tac|tail|tar|tee|time|timeout|top|touch|tr|traceroute|tsort|tty|umount|uname|unexpand|uniq|units|unrar|unshar|unzip|update-grub|uptime|useradd|userdel|usermod|users|uudecode|uuencode|v|vcpkg|vdir|vi|vim|virsh|vmstat|wait|watch|wc|wget|whereis|which|who|whoami|write|xargs|xdg-open|yarn|yes|zenity|zip|zsh|zypper)(?=$|[)\s;|&])/,lookbehind:!0},keyword:{pattern:/(^|[\s;|&]|[<>]\()(?:case|do|done|elif|else|esac|fi|for|function|if|in|select|then|until|while)(?=$|[)\s;|&])/,lookbehind:!0},builtin:{pattern:/(^|[\s;|&]|[<>]\()(?:\.|:|alias|bind|break|builtin|caller|cd|command|continue|declare|echo|enable|eval|exec|exit|export|getopts|hash|help|let|local|logout|mapfile|printf|pwd|read|readarray|readonly|return|set|shift|shopt|source|test|times|trap|type|typeset|ulimit|umask|unalias|unset)(?=$|[)\s;|&])/,lookbehind:!0,alias:"class-name"},boolean:{pattern:/(^|[\s;|&]|[<>]\()(?:false|true)(?=$|[)\s;|&])/,lookbehind:!0},"file-descriptor":{pattern:/\B&\d\b/,alias:"important"},operator:{pattern:/\d?<>|>\||\+=|=[=~]?|!=?|<<[<-]?|[&\d]?>>|\d[<>]&?|[<>][&=]?|&[>&]?|\|[&|]?/,inside:{"file-descriptor":{pattern:/^\d/,alias:"important"}}},punctuation:/\$?\(\(?|\)\)?|\.\.|[{}[\];\\]/,number:{pattern:/(^|\s)(?:[1-9]\d*|0)(?:[.,]\d+)?\b/,lookbehind:!0}},u.inside=t.languages.bash;for(var n=["comment","function-name","for-or-select","assign-left","parameter","string","environment","function","keyword","builtin","boolean","file-descriptor","operator","punctuation","number"],a=r.variable[1].inside,i=0;i<n.length;i++)a[n[i]]=t.languages.bash[n[i]];t.languages.sh=t.languages.bash,t.languages.shell=t.languages.bash;})(Prism);const O0='<svg class="md-link-icon" viewBox="0 0 16 16" version="1.1" width="16" height="16" aria-hidden="true" fill="currentColor"><path d="m7.775 3.275 1.25-1.25a3.5 3.5 0 1 1 4.95 4.95l-2.5 2.5a3.5 3.5 0 0 1-4.95 0 .751.751 0 0 1 .018-1.042.751.751 0 0 1 1.042-.018 1.998 1.998 0 0 0 2.83 0l2.5-2.5a2.002 2.002 0 0 0-2.83-2.83l-1.25 1.25a.751.751 0 0 1-1.042-.018.751.751 0 0 1-.018-1.042Zm-4.69 9.64a1.998 1.998 0 0 0 2.83 0l1.25-1.25a.751.751 0 0 1 1.042.018.751.751 0 0 1 .018 1.042l-1.25 1.25a3.5 3.5 0 1 1-4.95-4.95l2.5-2.5a3.5 3.5 0 0 1 4.95 0 .751.751 0 0 1-.018 1.042.751.751 0 0 1-1.042.018 1.998 1.998 0 0 0-2.83 0l-2.5 2.5a1.998 1.998 0 0 0 0 2.83Z"></path></svg>',q0=`
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 15 15" color="currentColor" aria-hidden="true" aria-label="Copy" stroke-width="1.3" width="15" height="15">
  <path fill="currentColor" d="M12.728 4.545v8.182H4.545V4.545zm0 -0.909H4.545a0.909 0.909 0 0 0 -0.909 0.909v8.182a0.909 0.909 0 0 0 0.909 0.909h8.182a0.909 0.909 0 0 0 0.909 -0.909V4.545a0.909 0.909 0 0 0 -0.909 -0.909"/>
  <path fill="currentColor" d="M1.818 8.182H0.909V1.818a0.909 0.909 0 0 1 0.909 -0.909h6.364v0.909H1.818Z"/>
</svg>

`,R0=`<svg xmlns="http://www.w3.org/2000/svg" width="17" height="17" viewBox="0 0 17 17" aria-hidden="true" aria-label="Copied" fill="none" stroke="currentColor" stroke-width="1.3">
  <path d="m13.813 4.781 -7.438 7.438 -3.188 -3.188"/>
</svg>
`,Iu=`<button title="copy" class="copy_code_button">
  <span class="copy-text">${q0}</span>
  <span class="check">${R0}</span>
</button>`,ot$2=/[&<>"']/,P0=new RegExp(ot$2.source,"g"),lt$3=/[<>"']|&(?!(#\d{1,7}|#[Xx][a-fA-F0-9]{1,6}|\w+);)/,M0=new RegExp(lt$3.source,"g"),H0={"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"},Nu=t=>H0[t]||"";function eu(t,e){if(e){if(ot$2.test(t))return t.replace(P0,Nu)}else if(lt$3.test(t))return t.replace(M0,Nu);return t}function j0(t){const e=t.map(u=>({start:new RegExp(u.left.replace(/[-\/\\^$*+?.()|[\]{}]/g,"\\$&")),end:new RegExp(u.right.replace(/[-\/\\^$*+?.()|[\]{}]/g,"\\$&"))}));return {name:"latex",level:"block",start(u){for(const r of e){const n=u.match(r.start);if(n)return n.index}return -1},tokenizer(u,r){for(const n of e){const a=new RegExp(`${n.start.source}([\\s\\S]+?)${n.end.source}`).exec(u);if(a)return {type:"latex",raw:a[0],text:a[1].trim()}}},renderer(u){return `<div class="latex-block">${u.text}</div>`}}}function z0(){return {name:"mermaid",level:"block",start(t){return t.match(/^```mermaid\s*\n/)?.index},tokenizer(t){const e=/^```mermaid\s*\n([\s\S]*?)```\s*(?:\n|$)/.exec(t);if(e)return {type:"mermaid",raw:e[0],text:e[1].trim()}},renderer(t){return `<div class="mermaid">${t.text}</div>
`}}}const U0={code(t,e,u){const r=(e??"").match(/\S*/)?.[0]??"";return t=t.replace(/\n$/,"")+`
`,!r||r==="mermaid"?'<div class="code_wrap">'+Iu+"<pre><code>"+(u?t:eu(t,!0))+`</code></pre></div>
`:'<div class="code_wrap">'+Iu+'<pre><code class="language-'+eu(r)+'">'+(u?t:eu(t,!0))+`</code></pre></div>
`}},$0=new hu;function V0({header_links:t,line_breaks:e,latex_delimiters:u}){const r=new nt$2;r.use({gfm:!0,pedantic:!1,breaks:e},C0({highlight:(i,l)=>V$1.languages?.[l]?V$1.highlight(i,V$1.languages[l],l):i}),{renderer:U0}),t&&(r.use(N0()),r.use({extensions:[{name:"heading",level:"block",renderer(i){const l=i.raw.toLowerCase().trim().replace(/<[!\/a-z].*?>/gi,""),o="h"+$0.slug(l),d=i.depth,f=this.parser.parseInline(i.tokens);return `<h${d} id="${o}"><a class="md-header-anchor" href="#${o}">${O0}</a>${f}</h${d}>
`}}]}));const n=z0(),a=j0(u);return r.use({extensions:[n,a]}),r}var dt$2={},Ee={},bu={},we$1={},pu={};Object.defineProperty(pu,"__esModule",{value:!0});pu.default=new Uint16Array('ᵁ<Õıʊҝջאٵ۞ޢߖࠏ੊ઑඡ๭༉༦჊ረዡᐕᒝᓃᓟᔥ\0\0\0\0\0\0ᕫᛍᦍᰒᷝ὾⁠↰⊍⏀⏻⑂⠤⤒ⴈ⹈⿎〖㊺㘹㞬㣾㨨㩱㫠㬮ࠀEMabcfglmnoprstu\\bfms¦³¹ÈÏlig耻Æ䃆P耻&䀦cute耻Á䃁reve;䄂Āiyx}rc耻Â䃂;䐐r;쀀𝔄rave耻À䃀pha;䎑acr;䄀d;橓Āgp¡on;䄄f;쀀𝔸plyFunction;恡ing耻Å䃅Ācs¾Ãr;쀀𝒜ign;扔ilde耻Ã䃃ml耻Ä䃄ЀaceforsuåûþėĜĢħĪĀcrêòkslash;或Ŷöø;櫧ed;挆y;䐑ƀcrtąċĔause;戵noullis;愬a;䎒r;쀀𝔅pf;쀀𝔹eve;䋘còēmpeq;扎܀HOacdefhilorsuōőŖƀƞƢƵƷƺǜȕɳɸɾcy;䐧PY耻©䂩ƀcpyŝŢźute;䄆Ā;iŧŨ拒talDifferentialD;慅leys;愭ȀaeioƉƎƔƘron;䄌dil耻Ç䃇rc;䄈nint;戰ot;䄊ĀdnƧƭilla;䂸terDot;䂷òſi;䎧rcleȀDMPTǇǋǑǖot;抙inus;抖lus;投imes;抗oĀcsǢǸkwiseContourIntegral;戲eCurlyĀDQȃȏoubleQuote;思uote;怙ȀlnpuȞȨɇɕonĀ;eȥȦ户;橴ƀgitȯȶȺruent;扡nt;戯ourIntegral;戮ĀfrɌɎ;愂oduct;成nterClockwiseContourIntegral;戳oss;樯cr;쀀𝒞pĀ;Cʄʅ拓ap;才րDJSZacefiosʠʬʰʴʸˋ˗ˡ˦̳ҍĀ;oŹʥtrahd;椑cy;䐂cy;䐅cy;䐏ƀgrsʿ˄ˇger;怡r;憡hv;櫤Āayː˕ron;䄎;䐔lĀ;t˝˞戇a;䎔r;쀀𝔇Āaf˫̧Ācm˰̢riticalȀADGT̖̜̀̆cute;䂴oŴ̋̍;䋙bleAcute;䋝rave;䁠ilde;䋜ond;拄ferentialD;慆Ѱ̽\0\0\0͔͂\0Ѕf;쀀𝔻ƀ;DE͈͉͍䂨ot;惜qual;扐blèCDLRUVͣͲ΂ϏϢϸontourIntegraìȹoɴ͹\0\0ͻ»͉nArrow;懓Āeo·ΤftƀARTΐΖΡrrow;懐ightArrow;懔eåˊngĀLRΫτeftĀARγιrrow;柸ightArrow;柺ightArrow;柹ightĀATϘϞrrow;懒ee;抨pɁϩ\0\0ϯrrow;懑ownArrow;懕erticalBar;戥ǹABLRTaВЪаўѿͼrrowƀ;BUНОТ憓ar;椓pArrow;懵reve;䌑eft˒к\0ц\0ѐightVector;楐eeVector;楞ectorĀ;Bљњ憽ar;楖ightǔѧ\0ѱeeVector;楟ectorĀ;BѺѻ懁ar;楗eeĀ;A҆҇护rrow;憧ĀctҒҗr;쀀𝒟rok;䄐ࠀNTacdfglmopqstuxҽӀӄӋӞӢӧӮӵԡԯԶՒ՝ՠեG;䅊H耻Ð䃐cute耻É䃉ƀaiyӒӗӜron;䄚rc耻Ê䃊;䐭ot;䄖r;쀀𝔈rave耻È䃈ement;戈ĀapӺӾcr;䄒tyɓԆ\0\0ԒmallSquare;旻erySmallSquare;斫ĀgpԦԪon;䄘f;쀀𝔼silon;䎕uĀaiԼՉlĀ;TՂՃ橵ilde;扂librium;懌Āci՗՚r;愰m;橳a;䎗ml耻Ë䃋Āipժկsts;戃onentialE;慇ʀcfiosօֈ֍ֲ׌y;䐤r;쀀𝔉lledɓ֗\0\0֣mallSquare;旼erySmallSquare;斪Ͱֺ\0ֿ\0\0ׄf;쀀𝔽All;戀riertrf;愱cò׋؀JTabcdfgorstר׬ׯ׺؀ؒؖ؛؝أ٬ٲcy;䐃耻>䀾mmaĀ;d׷׸䎓;䏜reve;䄞ƀeiy؇،ؐdil;䄢rc;䄜;䐓ot;䄠r;쀀𝔊;拙pf;쀀𝔾eater̀EFGLSTصلَٖٛ٦qualĀ;Lؾؿ扥ess;招ullEqual;执reater;檢ess;扷lantEqual;橾ilde;扳cr;쀀𝒢;扫ЀAacfiosuڅڋږڛڞڪھۊRDcy;䐪Āctڐڔek;䋇;䁞irc;䄤r;愌lbertSpace;愋ǰگ\0ڲf;愍izontalLine;攀Āctۃۅòکrok;䄦mpńېۘownHumðįqual;扏܀EJOacdfgmnostuۺ۾܃܇܎ܚܞܡܨ݄ݸދޏޕcy;䐕lig;䄲cy;䐁cute耻Í䃍Āiyܓܘrc耻Î䃎;䐘ot;䄰r;愑rave耻Ì䃌ƀ;apܠܯܿĀcgܴܷr;䄪inaryI;慈lieóϝǴ݉\0ݢĀ;eݍݎ戬Āgrݓݘral;戫section;拂isibleĀCTݬݲomma;恣imes;恢ƀgptݿރވon;䄮f;쀀𝕀a;䎙cr;愐ilde;䄨ǫޚ\0ޞcy;䐆l耻Ï䃏ʀcfosuެ޷޼߂ߐĀiyޱ޵rc;䄴;䐙r;쀀𝔍pf;쀀𝕁ǣ߇\0ߌr;쀀𝒥rcy;䐈kcy;䐄΀HJacfosߤߨ߽߬߱ࠂࠈcy;䐥cy;䐌ppa;䎚Āey߶߻dil;䄶;䐚r;쀀𝔎pf;쀀𝕂cr;쀀𝒦րJTaceflmostࠥࠩࠬࡐࡣ঳সে্਷ੇcy;䐉耻<䀼ʀcmnpr࠷࠼ࡁࡄࡍute;䄹bda;䎛g;柪lacetrf;愒r;憞ƀaeyࡗ࡜ࡡron;䄽dil;䄻;䐛Āfsࡨ॰tԀACDFRTUVarࡾࢩࢱࣦ࣠ࣼयज़ΐ४Ānrࢃ࢏gleBracket;柨rowƀ;BR࢙࢚࢞憐ar;懤ightArrow;懆eiling;挈oǵࢷ\0ࣃbleBracket;柦nǔࣈ\0࣒eeVector;楡ectorĀ;Bࣛࣜ懃ar;楙loor;挊ightĀAV࣯ࣵrrow;憔ector;楎Āerँगeƀ;AVउऊऐ抣rrow;憤ector;楚iangleƀ;BEतथऩ抲ar;槏qual;抴pƀDTVषूौownVector;楑eeVector;楠ectorĀ;Bॖॗ憿ar;楘ectorĀ;B॥०憼ar;楒ightáΜs̀EFGLSTॾঋকঝঢভqualGreater;拚ullEqual;扦reater;扶ess;檡lantEqual;橽ilde;扲r;쀀𝔏Ā;eঽা拘ftarrow;懚idot;䄿ƀnpw৔ਖਛgȀLRlr৞৷ਂਐeftĀAR০৬rrow;柵ightArrow;柷ightArrow;柶eftĀarγਊightáοightáϊf;쀀𝕃erĀLRਢਬeftArrow;憙ightArrow;憘ƀchtਾੀੂòࡌ;憰rok;䅁;扪Ѐacefiosuਗ਼੝੠੷੼અઋ઎p;椅y;䐜Ādl੥੯iumSpace;恟lintrf;愳r;쀀𝔐nusPlus;戓pf;쀀𝕄cò੶;䎜ҀJacefostuણધભીଔଙඑ඗ඞcy;䐊cute;䅃ƀaey઴હાron;䅇dil;䅅;䐝ƀgswે૰଎ativeƀMTV૓૟૨ediumSpace;怋hiĀcn૦૘ë૙eryThiî૙tedĀGL૸ଆreaterGreateòٳessLesóੈLine;䀊r;쀀𝔑ȀBnptଢନଷ଺reak;恠BreakingSpace;䂠f;愕ڀ;CDEGHLNPRSTV୕ୖ୪୼஡௫ఄ౞಄ದ೘ൡඅ櫬Āou୛୤ngruent;扢pCap;扭oubleVerticalBar;戦ƀlqxஃஊ஛ement;戉ualĀ;Tஒஓ扠ilde;쀀≂̸ists;戄reater΀;EFGLSTஶஷ஽௉௓௘௥扯qual;扱ullEqual;쀀≧̸reater;쀀≫̸ess;批lantEqual;쀀⩾̸ilde;扵umpń௲௽ownHump;쀀≎̸qual;쀀≏̸eĀfsఊధtTriangleƀ;BEచఛడ拪ar;쀀⧏̸qual;括s̀;EGLSTవశ఼ౄోౘ扮qual;扰reater;扸ess;쀀≪̸lantEqual;쀀⩽̸ilde;扴estedĀGL౨౹reaterGreater;쀀⪢̸essLess;쀀⪡̸recedesƀ;ESಒಓಛ技qual;쀀⪯̸lantEqual;拠ĀeiಫಹverseElement;戌ghtTriangleƀ;BEೋೌ೒拫ar;쀀⧐̸qual;拭ĀquೝഌuareSuĀbp೨೹setĀ;E೰ೳ쀀⊏̸qual;拢ersetĀ;Eഃആ쀀⊐̸qual;拣ƀbcpഓതൎsetĀ;Eഛഞ쀀⊂⃒qual;抈ceedsȀ;ESTലള഻െ抁qual;쀀⪰̸lantEqual;拡ilde;쀀≿̸ersetĀ;E൘൛쀀⊃⃒qual;抉ildeȀ;EFT൮൯൵ൿ扁qual;扄ullEqual;扇ilde;扉erticalBar;戤cr;쀀𝒩ilde耻Ñ䃑;䎝܀Eacdfgmoprstuvලෂ෉෕ෛ෠෧෼ขภยา฿ไlig;䅒cute耻Ó䃓Āiy෎ීrc耻Ô䃔;䐞blac;䅐r;쀀𝔒rave耻Ò䃒ƀaei෮ෲ෶cr;䅌ga;䎩cron;䎟pf;쀀𝕆enCurlyĀDQฎบoubleQuote;怜uote;怘;橔Āclวฬr;쀀𝒪ash耻Ø䃘iŬื฼de耻Õ䃕es;樷ml耻Ö䃖erĀBP๋๠Āar๐๓r;怾acĀek๚๜;揞et;掴arenthesis;揜Ҁacfhilors๿ງຊຏຒດຝະ໼rtialD;戂y;䐟r;쀀𝔓i;䎦;䎠usMinus;䂱Āipຢອncareplanåڝf;愙Ȁ;eio຺ູ໠໤檻cedesȀ;EST່້໏໚扺qual;檯lantEqual;扼ilde;找me;怳Ādp໩໮uct;戏ortionĀ;aȥ໹l;戝Āci༁༆r;쀀𝒫;䎨ȀUfos༑༖༛༟OT耻"䀢r;쀀𝔔pf;愚cr;쀀𝒬؀BEacefhiorsu༾གྷཇའཱིྦྷྪྭ႖ႩႴႾarr;椐G耻®䂮ƀcnrཎནབute;䅔g;柫rĀ;tཛྷཝ憠l;椖ƀaeyཧཬཱron;䅘dil;䅖;䐠Ā;vླྀཹ愜erseĀEUྂྙĀlq྇ྎement;戋uilibrium;懋pEquilibrium;楯r»ཹo;䎡ghtЀACDFTUVa࿁࿫࿳ဢဨၛႇϘĀnr࿆࿒gleBracket;柩rowƀ;BL࿜࿝࿡憒ar;懥eftArrow;懄eiling;按oǵ࿹\0စbleBracket;柧nǔည\0နeeVector;楝ectorĀ;Bဝသ懂ar;楕loor;挋Āerိ၃eƀ;AVဵံြ抢rrow;憦ector;楛iangleƀ;BEၐၑၕ抳ar;槐qual;抵pƀDTVၣၮၸownVector;楏eeVector;楜ectorĀ;Bႂႃ憾ar;楔ectorĀ;B႑႒懀ar;楓Āpuႛ႞f;愝ndImplies;楰ightarrow;懛ĀchႹႼr;愛;憱leDelayed;槴ڀHOacfhimoqstuფჱჷჽᄙᄞᅑᅖᅡᅧᆵᆻᆿĀCcჩხHcy;䐩y;䐨FTcy;䐬cute;䅚ʀ;aeiyᄈᄉᄎᄓᄗ檼ron;䅠dil;䅞rc;䅜;䐡r;쀀𝔖ortȀDLRUᄪᄴᄾᅉownArrow»ОeftArrow»࢚ightArrow»࿝pArrow;憑gma;䎣allCircle;战pf;쀀𝕊ɲᅭ\0\0ᅰt;戚areȀ;ISUᅻᅼᆉᆯ斡ntersection;抓uĀbpᆏᆞsetĀ;Eᆗᆘ抏qual;抑ersetĀ;Eᆨᆩ抐qual;抒nion;抔cr;쀀𝒮ar;拆ȀbcmpᇈᇛሉላĀ;sᇍᇎ拐etĀ;Eᇍᇕqual;抆ĀchᇠህeedsȀ;ESTᇭᇮᇴᇿ扻qual;檰lantEqual;扽ilde;承Tháྌ;我ƀ;esሒሓሣ拑rsetĀ;Eሜም抃qual;抇et»ሓրHRSacfhiorsሾቄ቉ቕ቞ቱቶኟዂወዑORN耻Þ䃞ADE;愢ĀHc቎ቒcy;䐋y;䐦Ābuቚቜ;䀉;䎤ƀaeyብቪቯron;䅤dil;䅢;䐢r;쀀𝔗Āeiቻ኉ǲኀ\0ኇefore;戴a;䎘Ācn኎ኘkSpace;쀀  Space;怉ldeȀ;EFTካኬኲኼ戼qual;扃ullEqual;扅ilde;扈pf;쀀𝕋ipleDot;惛Āctዖዛr;쀀𝒯rok;䅦ૡዷጎጚጦ\0ጬጱ\0\0\0\0\0ጸጽ፷ᎅ\0᏿ᐄᐊᐐĀcrዻጁute耻Ú䃚rĀ;oጇገ憟cir;楉rǣጓ\0጖y;䐎ve;䅬Āiyጞጣrc耻Û䃛;䐣blac;䅰r;쀀𝔘rave耻Ù䃙acr;䅪Ādiፁ፩erĀBPፈ፝Āarፍፐr;䁟acĀekፗፙ;揟et;掵arenthesis;揝onĀ;P፰፱拃lus;抎Āgp፻፿on;䅲f;쀀𝕌ЀADETadps᎕ᎮᎸᏄϨᏒᏗᏳrrowƀ;BDᅐᎠᎤar;椒ownArrow;懅ownArrow;憕quilibrium;楮eeĀ;AᏋᏌ报rrow;憥ownáϳerĀLRᏞᏨeftArrow;憖ightArrow;憗iĀ;lᏹᏺ䏒on;䎥ing;䅮cr;쀀𝒰ilde;䅨ml耻Ü䃜ҀDbcdefosvᐧᐬᐰᐳᐾᒅᒊᒐᒖash;披ar;櫫y;䐒ashĀ;lᐻᐼ抩;櫦Āerᑃᑅ;拁ƀbtyᑌᑐᑺar;怖Ā;iᑏᑕcalȀBLSTᑡᑥᑪᑴar;戣ine;䁼eparator;杘ilde;所ThinSpace;怊r;쀀𝔙pf;쀀𝕍cr;쀀𝒱dash;抪ʀcefosᒧᒬᒱᒶᒼirc;䅴dge;拀r;쀀𝔚pf;쀀𝕎cr;쀀𝒲Ȁfiosᓋᓐᓒᓘr;쀀𝔛;䎞pf;쀀𝕏cr;쀀𝒳ҀAIUacfosuᓱᓵᓹᓽᔄᔏᔔᔚᔠcy;䐯cy;䐇cy;䐮cute耻Ý䃝Āiyᔉᔍrc;䅶;䐫r;쀀𝔜pf;쀀𝕐cr;쀀𝒴ml;䅸ЀHacdefosᔵᔹᔿᕋᕏᕝᕠᕤcy;䐖cute;䅹Āayᕄᕉron;䅽;䐗ot;䅻ǲᕔ\0ᕛoWidtè૙a;䎖r;愨pf;愤cr;쀀𝒵௡ᖃᖊᖐ\0ᖰᖶᖿ\0\0\0\0ᗆᗛᗫᙟ᙭\0ᚕ᚛ᚲᚹ\0ᚾcute耻á䃡reve;䄃̀;Ediuyᖜᖝᖡᖣᖨᖭ戾;쀀∾̳;房rc耻â䃢te肻´̆;䐰lig耻æ䃦Ā;r²ᖺ;쀀𝔞rave耻à䃠ĀepᗊᗖĀfpᗏᗔsym;愵èᗓha;䎱ĀapᗟcĀclᗤᗧr;䄁g;樿ɤᗰ\0\0ᘊʀ;adsvᗺᗻᗿᘁᘇ戧nd;橕;橜lope;橘;橚΀;elmrszᘘᘙᘛᘞᘿᙏᙙ戠;榤e»ᘙsdĀ;aᘥᘦ戡ѡᘰᘲᘴᘶᘸᘺᘼᘾ;榨;榩;榪;榫;榬;榭;榮;榯tĀ;vᙅᙆ戟bĀ;dᙌᙍ抾;榝Āptᙔᙗh;戢»¹arr;捼Āgpᙣᙧon;䄅f;쀀𝕒΀;Eaeiop዁ᙻᙽᚂᚄᚇᚊ;橰cir;橯;扊d;手s;䀧roxĀ;e዁ᚒñᚃing耻å䃥ƀctyᚡᚦᚨr;쀀𝒶;䀪mpĀ;e዁ᚯñʈilde耻ã䃣ml耻ä䃤Āciᛂᛈoninôɲnt;樑ࠀNabcdefiklnoprsu᛭ᛱᜰ᜼ᝃᝈ᝸᝽០៦ᠹᡐᜍ᤽᥈ᥰot;櫭Ācrᛶ᜞kȀcepsᜀᜅᜍᜓong;扌psilon;䏶rime;怵imĀ;e᜚᜛戽q;拍Ŷᜢᜦee;抽edĀ;gᜬᜭ挅e»ᜭrkĀ;t፜᜷brk;掶Āoyᜁᝁ;䐱quo;怞ʀcmprtᝓ᝛ᝡᝤᝨausĀ;eĊĉptyv;榰séᜌnoõēƀahwᝯ᝱ᝳ;䎲;愶een;扬r;쀀𝔟g΀costuvwឍឝឳេ៕៛៞ƀaiuបពរðݠrc;旯p»፱ƀdptឤឨឭot;樀lus;樁imes;樂ɱឹ\0\0ើcup;樆ar;昅riangleĀdu៍្own;施p;斳plus;樄eåᑄåᒭarow;植ƀako៭ᠦᠵĀcn៲ᠣkƀlst៺֫᠂ozenge;槫riangleȀ;dlr᠒᠓᠘᠝斴own;斾eft;旂ight;斸k;搣Ʊᠫ\0ᠳƲᠯ\0ᠱ;斒;斑4;斓ck;斈ĀeoᠾᡍĀ;qᡃᡆ쀀=⃥uiv;쀀≡⃥t;挐Ȁptwxᡙᡞᡧᡬf;쀀𝕓Ā;tᏋᡣom»Ꮜtie;拈؀DHUVbdhmptuvᢅᢖᢪᢻᣗᣛᣬ᣿ᤅᤊᤐᤡȀLRlrᢎᢐᢒᢔ;敗;敔;敖;敓ʀ;DUduᢡᢢᢤᢦᢨ敐;敦;敩;敤;敧ȀLRlrᢳᢵᢷᢹ;敝;敚;敜;教΀;HLRhlrᣊᣋᣍᣏᣑᣓᣕ救;敬;散;敠;敫;敢;敟ox;槉ȀLRlrᣤᣦᣨᣪ;敕;敒;攐;攌ʀ;DUduڽ᣷᣹᣻᣽;敥;敨;攬;攴inus;抟lus;択imes;抠ȀLRlrᤙᤛᤝ᤟;敛;敘;攘;攔΀;HLRhlrᤰᤱᤳᤵᤷ᤻᤹攂;敪;敡;敞;攼;攤;攜Āevģ᥂bar耻¦䂦Ȁceioᥑᥖᥚᥠr;쀀𝒷mi;恏mĀ;e᜚᜜lƀ;bhᥨᥩᥫ䁜;槅sub;柈Ŭᥴ᥾lĀ;e᥹᥺怢t»᥺pƀ;Eeįᦅᦇ;檮Ā;qۜۛೡᦧ\0᧨ᨑᨕᨲ\0ᨷᩐ\0\0᪴\0\0᫁\0\0ᬡᬮ᭍᭒\0᯽\0ᰌƀcpr᦭ᦲ᧝ute;䄇̀;abcdsᦿᧀᧄ᧊᧕᧙戩nd;橄rcup;橉Āau᧏᧒p;橋p;橇ot;橀;쀀∩︀Āeo᧢᧥t;恁îړȀaeiu᧰᧻ᨁᨅǰ᧵\0᧸s;橍on;䄍dil耻ç䃧rc;䄉psĀ;sᨌᨍ橌m;橐ot;䄋ƀdmnᨛᨠᨦil肻¸ƭptyv;榲t脀¢;eᨭᨮ䂢räƲr;쀀𝔠ƀceiᨽᩀᩍy;䑇ckĀ;mᩇᩈ朓ark»ᩈ;䏇r΀;Ecefms᩟᩠ᩢᩫ᪤᪪᪮旋;槃ƀ;elᩩᩪᩭ䋆q;扗eɡᩴ\0\0᪈rrowĀlr᩼᪁eft;憺ight;憻ʀRSacd᪒᪔᪖᪚᪟»ཇ;擈st;抛irc;抚ash;抝nint;樐id;櫯cir;槂ubsĀ;u᪻᪼晣it»᪼ˬ᫇᫔᫺\0ᬊonĀ;eᫍᫎ䀺Ā;qÇÆɭ᫙\0\0᫢aĀ;t᫞᫟䀬;䁀ƀ;fl᫨᫩᫫戁îᅠeĀmx᫱᫶ent»᫩eóɍǧ᫾\0ᬇĀ;dኻᬂot;橭nôɆƀfryᬐᬔᬗ;쀀𝕔oäɔ脀©;sŕᬝr;愗Āaoᬥᬩrr;憵ss;朗Ācuᬲᬷr;쀀𝒸Ābpᬼ᭄Ā;eᭁᭂ櫏;櫑Ā;eᭉᭊ櫐;櫒dot;拯΀delprvw᭠᭬᭷ᮂᮬᯔ᯹arrĀlr᭨᭪;椸;椵ɰ᭲\0\0᭵r;拞c;拟arrĀ;p᭿ᮀ憶;椽̀;bcdosᮏᮐᮖᮡᮥᮨ截rcap;橈Āauᮛᮞp;橆p;橊ot;抍r;橅;쀀∪︀Ȁalrv᮵ᮿᯞᯣrrĀ;mᮼᮽ憷;椼yƀevwᯇᯔᯘqɰᯎ\0\0ᯒreã᭳uã᭵ee;拎edge;拏en耻¤䂤earrowĀlrᯮ᯳eft»ᮀight»ᮽeäᯝĀciᰁᰇoninôǷnt;戱lcty;挭ঀAHabcdefhijlorstuwz᰸᰻᰿ᱝᱩᱵᲊᲞᲬᲷ᳻᳿ᴍᵻᶑᶫᶻ᷆᷍rò΁ar;楥Ȁglrs᱈ᱍ᱒᱔ger;怠eth;愸òᄳhĀ;vᱚᱛ怐»ऊūᱡᱧarow;椏aã̕Āayᱮᱳron;䄏;䐴ƀ;ao̲ᱼᲄĀgrʿᲁr;懊tseq;橷ƀglmᲑᲔᲘ耻°䂰ta;䎴ptyv;榱ĀirᲣᲨsht;楿;쀀𝔡arĀlrᲳᲵ»ࣜ»သʀaegsv᳂͸᳖᳜᳠mƀ;oș᳊᳔ndĀ;ș᳑uit;晦amma;䏝in;拲ƀ;io᳧᳨᳸䃷de脀÷;o᳧ᳰntimes;拇nø᳷cy;䑒cɯᴆ\0\0ᴊrn;挞op;挍ʀlptuwᴘᴝᴢᵉᵕlar;䀤f;쀀𝕕ʀ;emps̋ᴭᴷᴽᵂqĀ;d͒ᴳot;扑inus;戸lus;戔quare;抡blebarwedgåúnƀadhᄮᵝᵧownarrowóᲃarpoonĀlrᵲᵶefôᲴighôᲶŢᵿᶅkaro÷གɯᶊ\0\0ᶎrn;挟op;挌ƀcotᶘᶣᶦĀryᶝᶡ;쀀𝒹;䑕l;槶rok;䄑Ādrᶰᶴot;拱iĀ;fᶺ᠖斿Āah᷀᷃ròЩaòྦangle;榦Āci᷒ᷕy;䑟grarr;柿ऀDacdefglmnopqrstuxḁḉḙḸոḼṉṡṾấắẽỡἪἷὄ὎὚ĀDoḆᴴoôᲉĀcsḎḔute耻é䃩ter;橮ȀaioyḢḧḱḶron;䄛rĀ;cḭḮ扖耻ê䃪lon;払;䑍ot;䄗ĀDrṁṅot;扒;쀀𝔢ƀ;rsṐṑṗ檚ave耻è䃨Ā;dṜṝ檖ot;檘Ȁ;ilsṪṫṲṴ檙nters;揧;愓Ā;dṹṺ檕ot;檗ƀapsẅẉẗcr;䄓tyƀ;svẒẓẕ戅et»ẓpĀ1;ẝẤĳạả;怄;怅怃ĀgsẪẬ;䅋p;怂ĀgpẴẸon;䄙f;쀀𝕖ƀalsỄỎỒrĀ;sỊị拕l;槣us;橱iƀ;lvỚớở䎵on»ớ;䏵ȀcsuvỪỳἋἣĀioữḱrc»Ḯɩỹ\0\0ỻíՈantĀglἂἆtr»ṝess»Ṻƀaeiἒ἖Ἒls;䀽st;扟vĀ;DȵἠD;橸parsl;槥ĀDaἯἳot;打rr;楱ƀcdiἾὁỸr;愯oô͒ĀahὉὋ;䎷耻ð䃰Āmrὓὗl耻ë䃫o;悬ƀcipὡὤὧl;䀡sôծĀeoὬὴctatioîՙnentialåչৡᾒ\0ᾞ\0ᾡᾧ\0\0ῆῌ\0ΐ\0ῦῪ \0 ⁚llingdotseñṄy;䑄male;晀ƀilrᾭᾳ῁lig;耀ﬃɩᾹ\0\0᾽g;耀ﬀig;耀ﬄ;쀀𝔣lig;耀ﬁlig;쀀fjƀaltῙ῜ῡt;晭ig;耀ﬂns;斱of;䆒ǰ΅\0ῳf;쀀𝕗ĀakֿῷĀ;vῼ´拔;櫙artint;樍Āao‌⁕Ācs‑⁒α‚‰‸⁅⁈\0⁐β•‥‧‪‬\0‮耻½䂽;慓耻¼䂼;慕;慙;慛Ƴ‴\0‶;慔;慖ʴ‾⁁\0\0⁃耻¾䂾;慗;慜5;慘ƶ⁌\0⁎;慚;慝8;慞l;恄wn;挢cr;쀀𝒻ࢀEabcdefgijlnorstv₂₉₟₥₰₴⃰⃵⃺⃿℃ℒℸ̗ℾ⅒↞Ā;lٍ₇;檌ƀcmpₐₕ₝ute;䇵maĀ;dₜ᳚䎳;檆reve;䄟Āiy₪₮rc;䄝;䐳ot;䄡Ȁ;lqsؾق₽⃉ƀ;qsؾٌ⃄lanô٥Ȁ;cdl٥⃒⃥⃕c;檩otĀ;o⃜⃝檀Ā;l⃢⃣檂;檄Ā;e⃪⃭쀀⋛︀s;檔r;쀀𝔤Ā;gٳ؛mel;愷cy;䑓Ȁ;Eajٚℌℎℐ;檒;檥;檤ȀEaesℛℝ℩ℴ;扩pĀ;p℣ℤ檊rox»ℤĀ;q℮ℯ檈Ā;q℮ℛim;拧pf;쀀𝕘Āci⅃ⅆr;愊mƀ;el٫ⅎ⅐;檎;檐茀>;cdlqr׮ⅠⅪⅮⅳⅹĀciⅥⅧ;檧r;橺ot;拗Par;榕uest;橼ʀadelsↄⅪ←ٖ↛ǰ↉\0↎proø₞r;楸qĀlqؿ↖lesó₈ií٫Āen↣↭rtneqq;쀀≩︀Å↪ԀAabcefkosy⇄⇇⇱⇵⇺∘∝∯≨≽ròΠȀilmr⇐⇔⇗⇛rsðᒄf»․ilôکĀdr⇠⇤cy;䑊ƀ;cwࣴ⇫⇯ir;楈;憭ar;意irc;䄥ƀalr∁∎∓rtsĀ;u∉∊晥it»∊lip;怦con;抹r;쀀𝔥sĀew∣∩arow;椥arow;椦ʀamopr∺∾≃≞≣rr;懿tht;戻kĀlr≉≓eftarrow;憩ightarrow;憪f;쀀𝕙bar;怕ƀclt≯≴≸r;쀀𝒽asè⇴rok;䄧Ābp⊂⊇ull;恃hen»ᱛૡ⊣\0⊪\0⊸⋅⋎\0⋕⋳\0\0⋸⌢⍧⍢⍿\0⎆⎪⎴cute耻í䃭ƀ;iyݱ⊰⊵rc耻î䃮;䐸Ācx⊼⊿y;䐵cl耻¡䂡ĀfrΟ⋉;쀀𝔦rave耻ì䃬Ȁ;inoܾ⋝⋩⋮Āin⋢⋦nt;樌t;戭fin;槜ta;愩lig;䄳ƀaop⋾⌚⌝ƀcgt⌅⌈⌗r;䄫ƀelpܟ⌏⌓inåގarôܠh;䄱f;抷ed;䆵ʀ;cfotӴ⌬⌱⌽⍁are;愅inĀ;t⌸⌹戞ie;槝doô⌙ʀ;celpݗ⍌⍐⍛⍡al;抺Āgr⍕⍙eróᕣã⍍arhk;樗rod;樼Ȁcgpt⍯⍲⍶⍻y;䑑on;䄯f;쀀𝕚a;䎹uest耻¿䂿Āci⎊⎏r;쀀𝒾nʀ;EdsvӴ⎛⎝⎡ӳ;拹ot;拵Ā;v⎦⎧拴;拳Ā;iݷ⎮lde;䄩ǫ⎸\0⎼cy;䑖l耻ï䃯̀cfmosu⏌⏗⏜⏡⏧⏵Āiy⏑⏕rc;䄵;䐹r;쀀𝔧ath;䈷pf;쀀𝕛ǣ⏬\0⏱r;쀀𝒿rcy;䑘kcy;䑔Ѐacfghjos␋␖␢␧␭␱␵␻ppaĀ;v␓␔䎺;䏰Āey␛␠dil;䄷;䐺r;쀀𝔨reen;䄸cy;䑅cy;䑜pf;쀀𝕜cr;쀀𝓀஀ABEHabcdefghjlmnoprstuv⑰⒁⒆⒍⒑┎┽╚▀♎♞♥♹♽⚚⚲⛘❝❨➋⟀⠁⠒ƀart⑷⑺⑼rò৆òΕail;椛arr;椎Ā;gঔ⒋;檋ar;楢ॣ⒥\0⒪\0⒱\0\0\0\0\0⒵Ⓔ\0ⓆⓈⓍ\0⓹ute;䄺mptyv;榴raîࡌbda;䎻gƀ;dlࢎⓁⓃ;榑åࢎ;檅uo耻«䂫rЀ;bfhlpst࢙ⓞⓦⓩ⓫⓮⓱⓵Ā;f࢝ⓣs;椟s;椝ë≒p;憫l;椹im;楳l;憢ƀ;ae⓿─┄檫il;椙Ā;s┉┊檭;쀀⪭︀ƀabr┕┙┝rr;椌rk;杲Āak┢┬cĀek┨┪;䁻;䁛Āes┱┳;榋lĀdu┹┻;榏;榍Ȁaeuy╆╋╖╘ron;䄾Ādi═╔il;䄼ìࢰâ┩;䐻Ȁcqrs╣╦╭╽a;椶uoĀ;rนᝆĀdu╲╷har;楧shar;楋h;憲ʀ;fgqs▋▌উ◳◿扤tʀahlrt▘▤▷◂◨rrowĀ;t࢙□aé⓶arpoonĀdu▯▴own»њp»०eftarrows;懇ightƀahs◍◖◞rrowĀ;sࣴࢧarpoonó྘quigarro÷⇰hreetimes;拋ƀ;qs▋ও◺lanôবʀ;cdgsব☊☍☝☨c;檨otĀ;o☔☕橿Ā;r☚☛檁;檃Ā;e☢☥쀀⋚︀s;檓ʀadegs☳☹☽♉♋pproøⓆot;拖qĀgq♃♅ôউgtò⒌ôছiíলƀilr♕࣡♚sht;楼;쀀𝔩Ā;Eজ♣;檑š♩♶rĀdu▲♮Ā;l॥♳;楪lk;斄cy;䑙ʀ;achtੈ⚈⚋⚑⚖rò◁orneòᴈard;楫ri;旺Āio⚟⚤dot;䅀ustĀ;a⚬⚭掰che»⚭ȀEaes⚻⚽⛉⛔;扨pĀ;p⛃⛄檉rox»⛄Ā;q⛎⛏檇Ā;q⛎⚻im;拦Ѐabnoptwz⛩⛴⛷✚✯❁❇❐Ānr⛮⛱g;柬r;懽rëࣁgƀlmr⛿✍✔eftĀar০✇ightá৲apsto;柼ightá৽parrowĀlr✥✩efô⓭ight;憬ƀafl✶✹✽r;榅;쀀𝕝us;樭imes;樴š❋❏st;戗áፎƀ;ef❗❘᠀旊nge»❘arĀ;l❤❥䀨t;榓ʀachmt❳❶❼➅➇ròࢨorneòᶌarĀ;d྘➃;業;怎ri;抿̀achiqt➘➝ੀ➢➮➻quo;怹r;쀀𝓁mƀ;egল➪➬;檍;檏Ābu┪➳oĀ;rฟ➹;怚rok;䅂萀<;cdhilqrࠫ⟒☹⟜⟠⟥⟪⟰Āci⟗⟙;檦r;橹reå◲mes;拉arr;楶uest;橻ĀPi⟵⟹ar;榖ƀ;ef⠀भ᠛旃rĀdu⠇⠍shar;楊har;楦Āen⠗⠡rtneqq;쀀≨︀Å⠞܀Dacdefhilnopsu⡀⡅⢂⢎⢓⢠⢥⢨⣚⣢⣤ઃ⣳⤂Dot;戺Ȁclpr⡎⡒⡣⡽r耻¯䂯Āet⡗⡙;時Ā;e⡞⡟朠se»⡟Ā;sျ⡨toȀ;dluျ⡳⡷⡻owîҌefôएðᏑker;斮Āoy⢇⢌mma;権;䐼ash;怔asuredangle»ᘦr;쀀𝔪o;愧ƀcdn⢯⢴⣉ro耻µ䂵Ȁ;acdᑤ⢽⣀⣄sôᚧir;櫰ot肻·Ƶusƀ;bd⣒ᤃ⣓戒Ā;uᴼ⣘;横ţ⣞⣡p;櫛ò−ðઁĀdp⣩⣮els;抧f;쀀𝕞Āct⣸⣽r;쀀𝓂pos»ᖝƀ;lm⤉⤊⤍䎼timap;抸ఀGLRVabcdefghijlmoprstuvw⥂⥓⥾⦉⦘⧚⧩⨕⨚⩘⩝⪃⪕⪤⪨⬄⬇⭄⭿⮮ⰴⱧⱼ⳩Āgt⥇⥋;쀀⋙̸Ā;v⥐௏쀀≫⃒ƀelt⥚⥲⥶ftĀar⥡⥧rrow;懍ightarrow;懎;쀀⋘̸Ā;v⥻ే쀀≪⃒ightarrow;懏ĀDd⦎⦓ash;抯ash;抮ʀbcnpt⦣⦧⦬⦱⧌la»˞ute;䅄g;쀀∠⃒ʀ;Eiop඄⦼⧀⧅⧈;쀀⩰̸d;쀀≋̸s;䅉roø඄urĀ;a⧓⧔普lĀ;s⧓ସǳ⧟\0⧣p肻 ଷmpĀ;e௹ఀʀaeouy⧴⧾⨃⨐⨓ǰ⧹\0⧻;橃on;䅈dil;䅆ngĀ;dൾ⨊ot;쀀⩭̸p;橂;䐽ash;怓΀;Aadqsxஒ⨩⨭⨻⩁⩅⩐rr;懗rĀhr⨳⨶k;椤Ā;oᏲᏰot;쀀≐̸uiöୣĀei⩊⩎ar;椨í஘istĀ;s஠டr;쀀𝔫ȀEest௅⩦⩹⩼ƀ;qs஼⩭௡ƀ;qs஼௅⩴lanô௢ií௪Ā;rஶ⪁»ஷƀAap⪊⪍⪑rò⥱rr;憮ar;櫲ƀ;svྍ⪜ྌĀ;d⪡⪢拼;拺cy;䑚΀AEadest⪷⪺⪾⫂⫅⫶⫹rò⥦;쀀≦̸rr;憚r;急Ȁ;fqs఻⫎⫣⫯tĀar⫔⫙rro÷⫁ightarro÷⪐ƀ;qs఻⪺⫪lanôౕĀ;sౕ⫴»శiíౝĀ;rవ⫾iĀ;eచథiäඐĀpt⬌⬑f;쀀𝕟膀¬;in⬙⬚⬶䂬nȀ;Edvஉ⬤⬨⬮;쀀⋹̸ot;쀀⋵̸ǡஉ⬳⬵;拷;拶iĀ;vಸ⬼ǡಸ⭁⭃;拾;拽ƀaor⭋⭣⭩rȀ;ast୻⭕⭚⭟lleì୻l;쀀⫽⃥;쀀∂̸lint;樔ƀ;ceಒ⭰⭳uåಥĀ;cಘ⭸Ā;eಒ⭽ñಘȀAait⮈⮋⮝⮧rò⦈rrƀ;cw⮔⮕⮙憛;쀀⤳̸;쀀↝̸ghtarrow»⮕riĀ;eೋೖ΀chimpqu⮽⯍⯙⬄୸⯤⯯Ȁ;cerല⯆ഷ⯉uå൅;쀀𝓃ortɭ⬅\0\0⯖ará⭖mĀ;e൮⯟Ā;q൴൳suĀbp⯫⯭å೸åഋƀbcp⯶ⰑⰙȀ;Ees⯿ⰀഢⰄ抄;쀀⫅̸etĀ;eഛⰋqĀ;qണⰀcĀ;eലⰗñസȀ;EesⰢⰣൟⰧ抅;쀀⫆̸etĀ;e൘ⰮqĀ;qൠⰣȀgilrⰽⰿⱅⱇìௗlde耻ñ䃱çృiangleĀlrⱒⱜeftĀ;eచⱚñదightĀ;eೋⱥñ೗Ā;mⱬⱭ䎽ƀ;esⱴⱵⱹ䀣ro;愖p;怇ҀDHadgilrsⲏⲔⲙⲞⲣⲰⲶⳓⳣash;抭arr;椄p;쀀≍⃒ash;抬ĀetⲨⲬ;쀀≥⃒;쀀>⃒nfin;槞ƀAetⲽⳁⳅrr;椂;쀀≤⃒Ā;rⳊⳍ쀀<⃒ie;쀀⊴⃒ĀAtⳘⳜrr;椃rie;쀀⊵⃒im;쀀∼⃒ƀAan⳰⳴ⴂrr;懖rĀhr⳺⳽k;椣Ā;oᏧᏥear;椧ቓ᪕\0\0\0\0\0\0\0\0\0\0\0\0\0ⴭ\0ⴸⵈⵠⵥ⵲ⶄᬇ\0\0ⶍⶫ\0ⷈⷎ\0ⷜ⸙⸫⸾⹃Ācsⴱ᪗ute耻ó䃳ĀiyⴼⵅrĀ;c᪞ⵂ耻ô䃴;䐾ʀabios᪠ⵒⵗǈⵚlac;䅑v;樸old;榼lig;䅓Ācr⵩⵭ir;榿;쀀𝔬ͯ⵹\0\0⵼\0ⶂn;䋛ave耻ò䃲;槁Ābmⶈ෴ar;榵Ȁacitⶕ⶘ⶥⶨrò᪀Āir⶝ⶠr;榾oss;榻nå๒;槀ƀaeiⶱⶵⶹcr;䅍ga;䏉ƀcdnⷀⷅǍron;䎿;榶pf;쀀𝕠ƀaelⷔ⷗ǒr;榷rp;榹΀;adiosvⷪⷫⷮ⸈⸍⸐⸖戨rò᪆Ȁ;efmⷷⷸ⸂⸅橝rĀ;oⷾⷿ愴f»ⷿ耻ª䂪耻º䂺gof;抶r;橖lope;橗;橛ƀclo⸟⸡⸧ò⸁ash耻ø䃸l;折iŬⸯ⸴de耻õ䃵esĀ;aǛ⸺s;樶ml耻ö䃶bar;挽ૡ⹞\0⹽\0⺀⺝\0⺢⺹\0\0⻋ຜ\0⼓\0\0⼫⾼\0⿈rȀ;astЃ⹧⹲຅脀¶;l⹭⹮䂶leìЃɩ⹸\0\0⹻m;櫳;櫽y;䐿rʀcimpt⺋⺏⺓ᡥ⺗nt;䀥od;䀮il;怰enk;怱r;쀀𝔭ƀimo⺨⺰⺴Ā;v⺭⺮䏆;䏕maô੶ne;明ƀ;tv⺿⻀⻈䏀chfork»´;䏖Āau⻏⻟nĀck⻕⻝kĀ;h⇴⻛;愎ö⇴sҀ;abcdemst⻳⻴ᤈ⻹⻽⼄⼆⼊⼎䀫cir;樣ir;樢Āouᵀ⼂;樥;橲n肻±ຝim;樦wo;樧ƀipu⼙⼠⼥ntint;樕f;쀀𝕡nd耻£䂣Ԁ;Eaceinosu່⼿⽁⽄⽇⾁⾉⾒⽾⾶;檳p;檷uå໙Ā;c໎⽌̀;acens່⽙⽟⽦⽨⽾pproø⽃urlyeñ໙ñ໎ƀaes⽯⽶⽺pprox;檹qq;檵im;拨iíໟmeĀ;s⾈ຮ怲ƀEas⽸⾐⽺ð⽵ƀdfp໬⾙⾯ƀals⾠⾥⾪lar;挮ine;挒urf;挓Ā;t໻⾴ï໻rel;抰Āci⿀⿅r;쀀𝓅;䏈ncsp;怈̀fiopsu⿚⋢⿟⿥⿫⿱r;쀀𝔮pf;쀀𝕢rime;恗cr;쀀𝓆ƀaeo⿸〉〓tĀei⿾々rnionóڰnt;樖stĀ;e【】䀿ñἙô༔઀ABHabcdefhilmnoprstux぀けさすムㄎㄫㅇㅢㅲㆎ㈆㈕㈤㈩㉘㉮㉲㊐㊰㊷ƀartぇおがròႳòϝail;検aròᱥar;楤΀cdenqrtとふへみわゔヌĀeuねぱ;쀀∽̱te;䅕iãᅮmptyv;榳gȀ;del࿑らるろ;榒;榥å࿑uo耻»䂻rր;abcfhlpstw࿜ガクシスゼゾダッデナp;極Ā;f࿠ゴs;椠;椳s;椞ë≝ð✮l;楅im;楴l;憣;憝Āaiパフil;椚oĀ;nホボ戶aló༞ƀabrョリヮrò៥rk;杳ĀakンヽcĀekヹ・;䁽;䁝Āes㄂㄄;榌lĀduㄊㄌ;榎;榐Ȁaeuyㄗㄜㄧㄩron;䅙Ādiㄡㄥil;䅗ì࿲âヺ;䑀Ȁclqsㄴㄷㄽㅄa;椷dhar;楩uoĀ;rȎȍh;憳ƀacgㅎㅟངlȀ;ipsླྀㅘㅛႜnåႻarôྩt;断ƀilrㅩဣㅮsht;楽;쀀𝔯ĀaoㅷㆆrĀduㅽㅿ»ѻĀ;l႑ㆄ;楬Ā;vㆋㆌ䏁;䏱ƀgns㆕ㇹㇼht̀ahlrstㆤㆰ㇂㇘㇤㇮rrowĀ;t࿜ㆭaéトarpoonĀduㆻㆿowîㅾp»႒eftĀah㇊㇐rrowó࿪arpoonóՑightarrows;應quigarro÷ニhreetimes;拌g;䋚ingdotseñἲƀahm㈍㈐㈓rò࿪aòՑ;怏oustĀ;a㈞㈟掱che»㈟mid;櫮Ȁabpt㈲㈽㉀㉒Ānr㈷㈺g;柭r;懾rëဃƀafl㉇㉊㉎r;榆;쀀𝕣us;樮imes;樵Āap㉝㉧rĀ;g㉣㉤䀩t;榔olint;樒arò㇣Ȁachq㉻㊀Ⴜ㊅quo;怺r;쀀𝓇Ābu・㊊oĀ;rȔȓƀhir㊗㊛㊠reåㇸmes;拊iȀ;efl㊪ၙᠡ㊫方tri;槎luhar;楨;愞ൡ㋕㋛㋟㌬㌸㍱\0㍺㎤\0\0㏬㏰\0㐨㑈㑚㒭㒱㓊㓱\0㘖\0\0㘳cute;䅛quï➺Ԁ;Eaceinpsyᇭ㋳㋵㋿㌂㌋㌏㌟㌦㌩;檴ǰ㋺\0㋼;檸on;䅡uåᇾĀ;dᇳ㌇il;䅟rc;䅝ƀEas㌖㌘㌛;檶p;檺im;择olint;樓iíሄ;䑁otƀ;be㌴ᵇ㌵担;橦΀Aacmstx㍆㍊㍗㍛㍞㍣㍭rr;懘rĀhr㍐㍒ë∨Ā;oਸ਼਴t耻§䂧i;䀻war;椩mĀin㍩ðnuóñt;朶rĀ;o㍶⁕쀀𝔰Ȁacoy㎂㎆㎑㎠rp;景Āhy㎋㎏cy;䑉;䑈rtɭ㎙\0\0㎜iäᑤaraì⹯耻­䂭Āgm㎨㎴maƀ;fv㎱㎲㎲䏃;䏂Ѐ;deglnprካ㏅㏉㏎㏖㏞㏡㏦ot;橪Ā;q኱ኰĀ;E㏓㏔檞;檠Ā;E㏛㏜檝;檟e;扆lus;樤arr;楲aròᄽȀaeit㏸㐈㐏㐗Āls㏽㐄lsetmé㍪hp;樳parsl;槤Ādlᑣ㐔e;挣Ā;e㐜㐝檪Ā;s㐢㐣檬;쀀⪬︀ƀflp㐮㐳㑂tcy;䑌Ā;b㐸㐹䀯Ā;a㐾㐿槄r;挿f;쀀𝕤aĀdr㑍ЂesĀ;u㑔㑕晠it»㑕ƀcsu㑠㑹㒟Āau㑥㑯pĀ;sᆈ㑫;쀀⊓︀pĀ;sᆴ㑵;쀀⊔︀uĀbp㑿㒏ƀ;esᆗᆜ㒆etĀ;eᆗ㒍ñᆝƀ;esᆨᆭ㒖etĀ;eᆨ㒝ñᆮƀ;afᅻ㒦ְrť㒫ֱ»ᅼaròᅈȀcemt㒹㒾㓂㓅r;쀀𝓈tmîñiì㐕aræᆾĀar㓎㓕rĀ;f㓔ឿ昆Āan㓚㓭ightĀep㓣㓪psiloîỠhé⺯s»⡒ʀbcmnp㓻㕞ሉ㖋㖎Ҁ;Edemnprs㔎㔏㔑㔕㔞㔣㔬㔱㔶抂;櫅ot;檽Ā;dᇚ㔚ot;櫃ult;櫁ĀEe㔨㔪;櫋;把lus;檿arr;楹ƀeiu㔽㕒㕕tƀ;en㔎㕅㕋qĀ;qᇚ㔏eqĀ;q㔫㔨m;櫇Ābp㕚㕜;櫕;櫓c̀;acensᇭ㕬㕲㕹㕻㌦pproø㋺urlyeñᇾñᇳƀaes㖂㖈㌛pproø㌚qñ㌗g;晪ڀ123;Edehlmnps㖩㖬㖯ሜ㖲㖴㗀㗉㗕㗚㗟㗨㗭耻¹䂹耻²䂲耻³䂳;櫆Āos㖹㖼t;檾ub;櫘Ā;dሢ㗅ot;櫄sĀou㗏㗒l;柉b;櫗arr;楻ult;櫂ĀEe㗤㗦;櫌;抋lus;櫀ƀeiu㗴㘉㘌tƀ;enሜ㗼㘂qĀ;qሢ㖲eqĀ;q㗧㗤m;櫈Ābp㘑㘓;櫔;櫖ƀAan㘜㘠㘭rr;懙rĀhr㘦㘨ë∮Ā;oਫ਩war;椪lig耻ß䃟௡㙑㙝㙠ዎ㙳㙹\0㙾㛂\0\0\0\0\0㛛㜃\0㜉㝬\0\0\0㞇ɲ㙖\0\0㙛get;挖;䏄rë๟ƀaey㙦㙫㙰ron;䅥dil;䅣;䑂lrec;挕r;쀀𝔱Ȁeiko㚆㚝㚵㚼ǲ㚋\0㚑eĀ4fኄኁaƀ;sv㚘㚙㚛䎸ym;䏑Ācn㚢㚲kĀas㚨㚮pproø዁im»ኬsðኞĀas㚺㚮ð዁rn耻þ䃾Ǭ̟㛆⋧es膀×;bd㛏㛐㛘䃗Ā;aᤏ㛕r;樱;樰ƀeps㛡㛣㜀á⩍Ȁ;bcf҆㛬㛰㛴ot;挶ir;櫱Ā;o㛹㛼쀀𝕥rk;櫚á㍢rime;怴ƀaip㜏㜒㝤dåቈ΀adempst㜡㝍㝀㝑㝗㝜㝟ngleʀ;dlqr㜰㜱㜶㝀㝂斵own»ᶻeftĀ;e⠀㜾ñम;扜ightĀ;e㊪㝋ñၚot;旬inus;樺lus;樹b;槍ime;樻ezium;揢ƀcht㝲㝽㞁Āry㝷㝻;쀀𝓉;䑆cy;䑛rok;䅧Āio㞋㞎xô᝷headĀlr㞗㞠eftarro÷ࡏightarrow»ཝऀAHabcdfghlmoprstuw㟐㟓㟗㟤㟰㟼㠎㠜㠣㠴㡑㡝㡫㢩㣌㣒㣪㣶ròϭar;楣Ācr㟜㟢ute耻ú䃺òᅐrǣ㟪\0㟭y;䑞ve;䅭Āiy㟵㟺rc耻û䃻;䑃ƀabh㠃㠆㠋ròᎭlac;䅱aòᏃĀir㠓㠘sht;楾;쀀𝔲rave耻ù䃹š㠧㠱rĀlr㠬㠮»ॗ»ႃlk;斀Āct㠹㡍ɯ㠿\0\0㡊rnĀ;e㡅㡆挜r»㡆op;挏ri;旸Āal㡖㡚cr;䅫肻¨͉Āgp㡢㡦on;䅳f;쀀𝕦̀adhlsuᅋ㡸㡽፲㢑㢠ownáᎳarpoonĀlr㢈㢌efô㠭ighô㠯iƀ;hl㢙㢚㢜䏅»ᏺon»㢚parrows;懈ƀcit㢰㣄㣈ɯ㢶\0\0㣁rnĀ;e㢼㢽挝r»㢽op;挎ng;䅯ri;旹cr;쀀𝓊ƀdir㣙㣝㣢ot;拰lde;䅩iĀ;f㜰㣨»᠓Āam㣯㣲rò㢨l耻ü䃼angle;榧ހABDacdeflnoprsz㤜㤟㤩㤭㦵㦸㦽㧟㧤㧨㧳㧹㧽㨁㨠ròϷarĀ;v㤦㤧櫨;櫩asèϡĀnr㤲㤷grt;榜΀eknprst㓣㥆㥋㥒㥝㥤㦖appá␕othinçẖƀhir㓫⻈㥙opô⾵Ā;hᎷ㥢ïㆍĀiu㥩㥭gmá㎳Ābp㥲㦄setneqĀ;q㥽㦀쀀⊊︀;쀀⫋︀setneqĀ;q㦏㦒쀀⊋︀;쀀⫌︀Āhr㦛㦟etá㚜iangleĀlr㦪㦯eft»थight»ၑy;䐲ash»ံƀelr㧄㧒㧗ƀ;beⷪ㧋㧏ar;抻q;扚lip;拮Ābt㧜ᑨaòᑩr;쀀𝔳tré㦮suĀbp㧯㧱»ജ»൙pf;쀀𝕧roð໻tré㦴Ācu㨆㨋r;쀀𝓋Ābp㨐㨘nĀEe㦀㨖»㥾nĀEe㦒㨞»㦐igzag;榚΀cefoprs㨶㨻㩖㩛㩔㩡㩪irc;䅵Ādi㩀㩑Ābg㩅㩉ar;機eĀ;qᗺ㩏;扙erp;愘r;쀀𝔴pf;쀀𝕨Ā;eᑹ㩦atèᑹcr;쀀𝓌ૣណ㪇\0㪋\0㪐㪛\0\0㪝㪨㪫㪯\0\0㫃㫎\0㫘ៜ៟tré៑r;쀀𝔵ĀAa㪔㪗ròσrò৶;䎾ĀAa㪡㪤ròθrò৫að✓is;拻ƀdptឤ㪵㪾Āfl㪺ឩ;쀀𝕩imåឲĀAa㫇㫊ròώròਁĀcq㫒ីr;쀀𝓍Āpt៖㫜ré។Ѐacefiosu㫰㫽㬈㬌㬑㬕㬛㬡cĀuy㫶㫻te耻ý䃽;䑏Āiy㬂㬆rc;䅷;䑋n耻¥䂥r;쀀𝔶cy;䑗pf;쀀𝕪cr;쀀𝓎Ācm㬦㬩y;䑎l耻ÿ䃿Ԁacdefhiosw㭂㭈㭔㭘㭤㭩㭭㭴㭺㮀cute;䅺Āay㭍㭒ron;䅾;䐷ot;䅼Āet㭝㭡træᕟa;䎶r;쀀𝔷cy;䐶grarr;懝pf;쀀𝕫cr;쀀𝓏Ājn㮅㮇;怍j;怌'.split("").map(function(t){return t.charCodeAt(0)}));var gu={};Object.defineProperty(gu,"__esModule",{value:!0});gu.default=new Uint16Array("Ȁaglq	\x1Bɭ\0\0p;䀦os;䀧t;䀾t;䀼uot;䀢".split("").map(function(t){return t.charCodeAt(0)}));var ru={};(function(t){var e;Object.defineProperty(t,"__esModule",{value:!0}),t.replaceCodePoint=t.fromCodePoint=void 0;var u=new Map([[0,65533],[128,8364],[130,8218],[131,402],[132,8222],[133,8230],[134,8224],[135,8225],[136,710],[137,8240],[138,352],[139,8249],[140,338],[142,381],[145,8216],[146,8217],[147,8220],[148,8221],[149,8226],[150,8211],[151,8212],[152,732],[153,8482],[154,353],[155,8250],[156,339],[158,382],[159,376]]);t.fromCodePoint=(e=String.fromCodePoint)!==null&&e!==void 0?e:function(a){var i="";return a>65535&&(a-=65536,i+=String.fromCharCode(a>>>10&1023|55296),a=56320|a&1023),i+=String.fromCharCode(a),i};function r(a){var i;return a>=55296&&a<=57343||a>1114111?65533:(i=u.get(a))!==null&&i!==void 0?i:a}t.replaceCodePoint=r;function n(a){return (0, t.fromCodePoint)(r(a))}t.default=n;})(ru);(function(t){var e=qs&&qs.__createBinding||(Object.create?function(b,D,A,k){k===void 0&&(k=A);var h=Object.getOwnPropertyDescriptor(D,A);(!h||("get"in h?!D.__esModule:h.writable||h.configurable))&&(h={enumerable:!0,get:function(){return D[A]}}),Object.defineProperty(b,k,h);}:function(b,D,A,k){k===void 0&&(k=A),b[k]=D[A];}),u=qs&&qs.__setModuleDefault||(Object.create?function(b,D){Object.defineProperty(b,"default",{enumerable:!0,value:D});}:function(b,D){b.default=D;}),r=qs&&qs.__importStar||function(b){if(b&&b.__esModule)return b;var D={};if(b!=null)for(var A in b)A!=="default"&&Object.prototype.hasOwnProperty.call(b,A)&&e(D,b,A);return u(D,b),D},n=qs&&qs.__importDefault||function(b){return b&&b.__esModule?b:{default:b}};Object.defineProperty(t,"__esModule",{value:!0}),t.decodeXML=t.decodeHTMLStrict=t.decodeHTMLAttribute=t.decodeHTML=t.determineBranch=t.EntityDecoder=t.DecodingMode=t.BinTrieFlags=t.fromCodePoint=t.replaceCodePoint=t.decodeCodePoint=t.xmlDecodeTree=t.htmlDecodeTree=void 0;var a=n(pu);t.htmlDecodeTree=a.default;var i=n(gu);t.xmlDecodeTree=i.default;var l=r(ru);t.decodeCodePoint=l.default;var o=ru;Object.defineProperty(t,"replaceCodePoint",{enumerable:!0,get:function(){return o.replaceCodePoint}}),Object.defineProperty(t,"fromCodePoint",{enumerable:!0,get:function(){return o.fromCodePoint}});var d;(function(b){b[b.NUM=35]="NUM",b[b.SEMI=59]="SEMI",b[b.EQUALS=61]="EQUALS",b[b.ZERO=48]="ZERO",b[b.NINE=57]="NINE",b[b.LOWER_A=97]="LOWER_A",b[b.LOWER_F=102]="LOWER_F",b[b.LOWER_X=120]="LOWER_X",b[b.LOWER_Z=122]="LOWER_Z",b[b.UPPER_A=65]="UPPER_A",b[b.UPPER_F=70]="UPPER_F",b[b.UPPER_Z=90]="UPPER_Z";})(d||(d={}));var f=32,p;(function(b){b[b.VALUE_LENGTH=49152]="VALUE_LENGTH",b[b.BRANCH_LENGTH=16256]="BRANCH_LENGTH",b[b.JUMP_TABLE=127]="JUMP_TABLE";})(p=t.BinTrieFlags||(t.BinTrieFlags={}));function s(b){return b>=d.ZERO&&b<=d.NINE}function c(b){return b>=d.UPPER_A&&b<=d.UPPER_F||b>=d.LOWER_A&&b<=d.LOWER_F}function x(b){return b>=d.UPPER_A&&b<=d.UPPER_Z||b>=d.LOWER_A&&b<=d.LOWER_Z||s(b)}function y(b){return b===d.EQUALS||x(b)}var v;(function(b){b[b.EntityStart=0]="EntityStart",b[b.NumericStart=1]="NumericStart",b[b.NumericDecimal=2]="NumericDecimal",b[b.NumericHex=3]="NumericHex",b[b.NamedEntity=4]="NamedEntity";})(v||(v={}));var E;(function(b){b[b.Legacy=0]="Legacy",b[b.Strict=1]="Strict",b[b.Attribute=2]="Attribute";})(E=t.DecodingMode||(t.DecodingMode={}));var C=function(){function b(D,A,k){this.decodeTree=D,this.emitCodePoint=A,this.errors=k,this.state=v.EntityStart,this.consumed=1,this.result=0,this.treeIndex=0,this.excess=1,this.decodeMode=E.Strict;}return b.prototype.startEntity=function(D){this.decodeMode=D,this.state=v.EntityStart,this.result=0,this.treeIndex=0,this.excess=1,this.consumed=1;},b.prototype.write=function(D,A){switch(this.state){case v.EntityStart:return D.charCodeAt(A)===d.NUM?(this.state=v.NumericStart,this.consumed+=1,this.stateNumericStart(D,A+1)):(this.state=v.NamedEntity,this.stateNamedEntity(D,A));case v.NumericStart:return this.stateNumericStart(D,A);case v.NumericDecimal:return this.stateNumericDecimal(D,A);case v.NumericHex:return this.stateNumericHex(D,A);case v.NamedEntity:return this.stateNamedEntity(D,A)}},b.prototype.stateNumericStart=function(D,A){return A>=D.length?-1:(D.charCodeAt(A)|f)===d.LOWER_X?(this.state=v.NumericHex,this.consumed+=1,this.stateNumericHex(D,A+1)):(this.state=v.NumericDecimal,this.stateNumericDecimal(D,A))},b.prototype.addToNumericResult=function(D,A,k,h){if(A!==k){var m=k-A;this.result=this.result*Math.pow(h,m)+parseInt(D.substr(A,m),h),this.consumed+=m;}},b.prototype.stateNumericHex=function(D,A){for(var k=A;A<D.length;){var h=D.charCodeAt(A);if(s(h)||c(h))A+=1;else return this.addToNumericResult(D,k,A,16),this.emitNumericEntity(h,3)}return this.addToNumericResult(D,k,A,16),-1},b.prototype.stateNumericDecimal=function(D,A){for(var k=A;A<D.length;){var h=D.charCodeAt(A);if(s(h))A+=1;else return this.addToNumericResult(D,k,A,10),this.emitNumericEntity(h,2)}return this.addToNumericResult(D,k,A,10),-1},b.prototype.emitNumericEntity=function(D,A){var k;if(this.consumed<=A)return (k=this.errors)===null||k===void 0||k.absenceOfDigitsInNumericCharacterReference(this.consumed),0;if(D===d.SEMI)this.consumed+=1;else if(this.decodeMode===E.Strict)return 0;return this.emitCodePoint((0, l.replaceCodePoint)(this.result),this.consumed),this.errors&&(D!==d.SEMI&&this.errors.missingSemicolonAfterCharacterReference(),this.errors.validateNumericCharacterReference(this.result)),this.consumed},b.prototype.stateNamedEntity=function(D,A){for(var k=this.decodeTree,h=k[this.treeIndex],m=(h&p.VALUE_LENGTH)>>14;A<D.length;A++,this.excess++){var g=D.charCodeAt(A);if(this.treeIndex=S(k,h,this.treeIndex+Math.max(1,m),g),this.treeIndex<0)return this.result===0||this.decodeMode===E.Attribute&&(m===0||y(g))?0:this.emitNotTerminatedNamedEntity();if(h=k[this.treeIndex],m=(h&p.VALUE_LENGTH)>>14,m!==0){if(g===d.SEMI)return this.emitNamedEntityData(this.treeIndex,m,this.consumed+this.excess);this.decodeMode!==E.Strict&&(this.result=this.treeIndex,this.consumed+=this.excess,this.excess=0);}}return -1},b.prototype.emitNotTerminatedNamedEntity=function(){var D,A=this,k=A.result,h=A.decodeTree,m=(h[k]&p.VALUE_LENGTH)>>14;return this.emitNamedEntityData(k,m,this.consumed),(D=this.errors)===null||D===void 0||D.missingSemicolonAfterCharacterReference(),this.consumed},b.prototype.emitNamedEntityData=function(D,A,k){var h=this.decodeTree;return this.emitCodePoint(A===1?h[D]&~p.VALUE_LENGTH:h[D+1],k),A===3&&this.emitCodePoint(h[D+2],k),k},b.prototype.end=function(){var D;switch(this.state){case v.NamedEntity:return this.result!==0&&(this.decodeMode!==E.Attribute||this.result===this.treeIndex)?this.emitNotTerminatedNamedEntity():0;case v.NumericDecimal:return this.emitNumericEntity(0,2);case v.NumericHex:return this.emitNumericEntity(0,3);case v.NumericStart:return (D=this.errors)===null||D===void 0||D.absenceOfDigitsInNumericCharacterReference(this.consumed),0;case v.EntityStart:return 0}},b}();t.EntityDecoder=C;function F(b){var D="",A=new C(b,function(k){return D+=(0, l.fromCodePoint)(k)});return function(h,m){for(var g=0,w=0;(w=h.indexOf("&",w))>=0;){D+=h.slice(g,w),A.startEntity(m);var j=A.write(h,w+1);if(j<0){g=w+A.end();break}g=w+j,w=j===0?g+1:g;}var H=D+h.slice(g);return D="",H}}function S(b,D,A,k){var h=(D&p.BRANCH_LENGTH)>>7,m=D&p.JUMP_TABLE;if(h===0)return m!==0&&k===m?A:-1;if(m){var g=k-m;return g<0||g>=h?-1:b[A+g]-1}for(var w=A,j=w+h-1;w<=j;){var H=w+j>>>1,P=b[H];if(P<k)w=H+1;else if(P>k)j=H-1;else return b[H+h]}return -1}t.determineBranch=S;var _=F(a.default),M=F(i.default);function U(b,D){return D===void 0&&(D=E.Legacy),_(b,D)}t.decodeHTML=U;function V(b){return _(b,E.Attribute)}t.decodeHTMLAttribute=V;function J(b){return _(b,E.Strict)}t.decodeHTMLStrict=J;function Q(b){return M(b,E.Strict)}t.decodeXML=Q;})(we$1);(function(t){Object.defineProperty(t,"__esModule",{value:!0}),t.QuoteType=void 0;var e=we$1,u;(function(s){s[s.Tab=9]="Tab",s[s.NewLine=10]="NewLine",s[s.FormFeed=12]="FormFeed",s[s.CarriageReturn=13]="CarriageReturn",s[s.Space=32]="Space",s[s.ExclamationMark=33]="ExclamationMark",s[s.Number=35]="Number",s[s.Amp=38]="Amp",s[s.SingleQuote=39]="SingleQuote",s[s.DoubleQuote=34]="DoubleQuote",s[s.Dash=45]="Dash",s[s.Slash=47]="Slash",s[s.Zero=48]="Zero",s[s.Nine=57]="Nine",s[s.Semi=59]="Semi",s[s.Lt=60]="Lt",s[s.Eq=61]="Eq",s[s.Gt=62]="Gt",s[s.Questionmark=63]="Questionmark",s[s.UpperA=65]="UpperA",s[s.LowerA=97]="LowerA",s[s.UpperF=70]="UpperF",s[s.LowerF=102]="LowerF",s[s.UpperZ=90]="UpperZ",s[s.LowerZ=122]="LowerZ",s[s.LowerX=120]="LowerX",s[s.OpeningSquareBracket=91]="OpeningSquareBracket";})(u||(u={}));var r;(function(s){s[s.Text=1]="Text",s[s.BeforeTagName=2]="BeforeTagName",s[s.InTagName=3]="InTagName",s[s.InSelfClosingTag=4]="InSelfClosingTag",s[s.BeforeClosingTagName=5]="BeforeClosingTagName",s[s.InClosingTagName=6]="InClosingTagName",s[s.AfterClosingTagName=7]="AfterClosingTagName",s[s.BeforeAttributeName=8]="BeforeAttributeName",s[s.InAttributeName=9]="InAttributeName",s[s.AfterAttributeName=10]="AfterAttributeName",s[s.BeforeAttributeValue=11]="BeforeAttributeValue",s[s.InAttributeValueDq=12]="InAttributeValueDq",s[s.InAttributeValueSq=13]="InAttributeValueSq",s[s.InAttributeValueNq=14]="InAttributeValueNq",s[s.BeforeDeclaration=15]="BeforeDeclaration",s[s.InDeclaration=16]="InDeclaration",s[s.InProcessingInstruction=17]="InProcessingInstruction",s[s.BeforeComment=18]="BeforeComment",s[s.CDATASequence=19]="CDATASequence",s[s.InSpecialComment=20]="InSpecialComment",s[s.InCommentLike=21]="InCommentLike",s[s.BeforeSpecialS=22]="BeforeSpecialS",s[s.SpecialStartSequence=23]="SpecialStartSequence",s[s.InSpecialTag=24]="InSpecialTag",s[s.BeforeEntity=25]="BeforeEntity",s[s.BeforeNumericEntity=26]="BeforeNumericEntity",s[s.InNamedEntity=27]="InNamedEntity",s[s.InNumericEntity=28]="InNumericEntity",s[s.InHexEntity=29]="InHexEntity";})(r||(r={}));function n(s){return s===u.Space||s===u.NewLine||s===u.Tab||s===u.FormFeed||s===u.CarriageReturn}function a(s){return s===u.Slash||s===u.Gt||n(s)}function i(s){return s>=u.Zero&&s<=u.Nine}function l(s){return s>=u.LowerA&&s<=u.LowerZ||s>=u.UpperA&&s<=u.UpperZ}function o(s){return s>=u.UpperA&&s<=u.UpperF||s>=u.LowerA&&s<=u.LowerF}var d;(function(s){s[s.NoValue=0]="NoValue",s[s.Unquoted=1]="Unquoted",s[s.Single=2]="Single",s[s.Double=3]="Double";})(d=t.QuoteType||(t.QuoteType={}));var f={Cdata:new Uint8Array([67,68,65,84,65,91]),CdataEnd:new Uint8Array([93,93,62]),CommentEnd:new Uint8Array([45,45,62]),ScriptEnd:new Uint8Array([60,47,115,99,114,105,112,116]),StyleEnd:new Uint8Array([60,47,115,116,121,108,101]),TitleEnd:new Uint8Array([60,47,116,105,116,108,101])},p=function(){function s(c,x){var y=c.xmlMode,v=y===void 0?!1:y,E=c.decodeEntities,C=E===void 0?!0:E;this.cbs=x,this.state=r.Text,this.buffer="",this.sectionStart=0,this.index=0,this.baseState=r.Text,this.isSpecial=!1,this.running=!0,this.offset=0,this.currentSequence=void 0,this.sequenceIndex=0,this.trieIndex=0,this.trieCurrent=0,this.entityResult=0,this.entityExcess=0,this.xmlMode=v,this.decodeEntities=C,this.entityTrie=v?e.xmlDecodeTree:e.htmlDecodeTree;}return s.prototype.reset=function(){this.state=r.Text,this.buffer="",this.sectionStart=0,this.index=0,this.baseState=r.Text,this.currentSequence=void 0,this.running=!0,this.offset=0;},s.prototype.write=function(c){this.offset+=this.buffer.length,this.buffer=c,this.parse();},s.prototype.end=function(){this.running&&this.finish();},s.prototype.pause=function(){this.running=!1;},s.prototype.resume=function(){this.running=!0,this.index<this.buffer.length+this.offset&&this.parse();},s.prototype.getIndex=function(){return this.index},s.prototype.getSectionStart=function(){return this.sectionStart},s.prototype.stateText=function(c){c===u.Lt||!this.decodeEntities&&this.fastForwardTo(u.Lt)?(this.index>this.sectionStart&&this.cbs.ontext(this.sectionStart,this.index),this.state=r.BeforeTagName,this.sectionStart=this.index):this.decodeEntities&&c===u.Amp&&(this.state=r.BeforeEntity);},s.prototype.stateSpecialStartSequence=function(c){var x=this.sequenceIndex===this.currentSequence.length,y=x?a(c):(c|32)===this.currentSequence[this.sequenceIndex];if(!y)this.isSpecial=!1;else if(!x){this.sequenceIndex++;return}this.sequenceIndex=0,this.state=r.InTagName,this.stateInTagName(c);},s.prototype.stateInSpecialTag=function(c){if(this.sequenceIndex===this.currentSequence.length){if(c===u.Gt||n(c)){var x=this.index-this.currentSequence.length;if(this.sectionStart<x){var y=this.index;this.index=x,this.cbs.ontext(this.sectionStart,x),this.index=y;}this.isSpecial=!1,this.sectionStart=x+2,this.stateInClosingTagName(c);return}this.sequenceIndex=0;}(c|32)===this.currentSequence[this.sequenceIndex]?this.sequenceIndex+=1:this.sequenceIndex===0?this.currentSequence===f.TitleEnd?this.decodeEntities&&c===u.Amp&&(this.state=r.BeforeEntity):this.fastForwardTo(u.Lt)&&(this.sequenceIndex=1):this.sequenceIndex=+(c===u.Lt);},s.prototype.stateCDATASequence=function(c){c===f.Cdata[this.sequenceIndex]?++this.sequenceIndex===f.Cdata.length&&(this.state=r.InCommentLike,this.currentSequence=f.CdataEnd,this.sequenceIndex=0,this.sectionStart=this.index+1):(this.sequenceIndex=0,this.state=r.InDeclaration,this.stateInDeclaration(c));},s.prototype.fastForwardTo=function(c){for(;++this.index<this.buffer.length+this.offset;)if(this.buffer.charCodeAt(this.index-this.offset)===c)return !0;return this.index=this.buffer.length+this.offset-1,!1},s.prototype.stateInCommentLike=function(c){c===this.currentSequence[this.sequenceIndex]?++this.sequenceIndex===this.currentSequence.length&&(this.currentSequence===f.CdataEnd?this.cbs.oncdata(this.sectionStart,this.index,2):this.cbs.oncomment(this.sectionStart,this.index,2),this.sequenceIndex=0,this.sectionStart=this.index+1,this.state=r.Text):this.sequenceIndex===0?this.fastForwardTo(this.currentSequence[0])&&(this.sequenceIndex=1):c!==this.currentSequence[this.sequenceIndex-1]&&(this.sequenceIndex=0);},s.prototype.isTagStartChar=function(c){return this.xmlMode?!a(c):l(c)},s.prototype.startSpecial=function(c,x){this.isSpecial=!0,this.currentSequence=c,this.sequenceIndex=x,this.state=r.SpecialStartSequence;},s.prototype.stateBeforeTagName=function(c){if(c===u.ExclamationMark)this.state=r.BeforeDeclaration,this.sectionStart=this.index+1;else if(c===u.Questionmark)this.state=r.InProcessingInstruction,this.sectionStart=this.index+1;else if(this.isTagStartChar(c)){var x=c|32;this.sectionStart=this.index,!this.xmlMode&&x===f.TitleEnd[2]?this.startSpecial(f.TitleEnd,3):this.state=!this.xmlMode&&x===f.ScriptEnd[2]?r.BeforeSpecialS:r.InTagName;}else c===u.Slash?this.state=r.BeforeClosingTagName:(this.state=r.Text,this.stateText(c));},s.prototype.stateInTagName=function(c){a(c)&&(this.cbs.onopentagname(this.sectionStart,this.index),this.sectionStart=-1,this.state=r.BeforeAttributeName,this.stateBeforeAttributeName(c));},s.prototype.stateBeforeClosingTagName=function(c){n(c)||(c===u.Gt?this.state=r.Text:(this.state=this.isTagStartChar(c)?r.InClosingTagName:r.InSpecialComment,this.sectionStart=this.index));},s.prototype.stateInClosingTagName=function(c){(c===u.Gt||n(c))&&(this.cbs.onclosetag(this.sectionStart,this.index),this.sectionStart=-1,this.state=r.AfterClosingTagName,this.stateAfterClosingTagName(c));},s.prototype.stateAfterClosingTagName=function(c){(c===u.Gt||this.fastForwardTo(u.Gt))&&(this.state=r.Text,this.baseState=r.Text,this.sectionStart=this.index+1);},s.prototype.stateBeforeAttributeName=function(c){c===u.Gt?(this.cbs.onopentagend(this.index),this.isSpecial?(this.state=r.InSpecialTag,this.sequenceIndex=0):this.state=r.Text,this.baseState=this.state,this.sectionStart=this.index+1):c===u.Slash?this.state=r.InSelfClosingTag:n(c)||(this.state=r.InAttributeName,this.sectionStart=this.index);},s.prototype.stateInSelfClosingTag=function(c){c===u.Gt?(this.cbs.onselfclosingtag(this.index),this.state=r.Text,this.baseState=r.Text,this.sectionStart=this.index+1,this.isSpecial=!1):n(c)||(this.state=r.BeforeAttributeName,this.stateBeforeAttributeName(c));},s.prototype.stateInAttributeName=function(c){(c===u.Eq||a(c))&&(this.cbs.onattribname(this.sectionStart,this.index),this.sectionStart=-1,this.state=r.AfterAttributeName,this.stateAfterAttributeName(c));},s.prototype.stateAfterAttributeName=function(c){c===u.Eq?this.state=r.BeforeAttributeValue:c===u.Slash||c===u.Gt?(this.cbs.onattribend(d.NoValue,this.index),this.state=r.BeforeAttributeName,this.stateBeforeAttributeName(c)):n(c)||(this.cbs.onattribend(d.NoValue,this.index),this.state=r.InAttributeName,this.sectionStart=this.index);},s.prototype.stateBeforeAttributeValue=function(c){c===u.DoubleQuote?(this.state=r.InAttributeValueDq,this.sectionStart=this.index+1):c===u.SingleQuote?(this.state=r.InAttributeValueSq,this.sectionStart=this.index+1):n(c)||(this.sectionStart=this.index,this.state=r.InAttributeValueNq,this.stateInAttributeValueNoQuotes(c));},s.prototype.handleInAttributeValue=function(c,x){c===x||!this.decodeEntities&&this.fastForwardTo(x)?(this.cbs.onattribdata(this.sectionStart,this.index),this.sectionStart=-1,this.cbs.onattribend(x===u.DoubleQuote?d.Double:d.Single,this.index),this.state=r.BeforeAttributeName):this.decodeEntities&&c===u.Amp&&(this.baseState=this.state,this.state=r.BeforeEntity);},s.prototype.stateInAttributeValueDoubleQuotes=function(c){this.handleInAttributeValue(c,u.DoubleQuote);},s.prototype.stateInAttributeValueSingleQuotes=function(c){this.handleInAttributeValue(c,u.SingleQuote);},s.prototype.stateInAttributeValueNoQuotes=function(c){n(c)||c===u.Gt?(this.cbs.onattribdata(this.sectionStart,this.index),this.sectionStart=-1,this.cbs.onattribend(d.Unquoted,this.index),this.state=r.BeforeAttributeName,this.stateBeforeAttributeName(c)):this.decodeEntities&&c===u.Amp&&(this.baseState=this.state,this.state=r.BeforeEntity);},s.prototype.stateBeforeDeclaration=function(c){c===u.OpeningSquareBracket?(this.state=r.CDATASequence,this.sequenceIndex=0):this.state=c===u.Dash?r.BeforeComment:r.InDeclaration;},s.prototype.stateInDeclaration=function(c){(c===u.Gt||this.fastForwardTo(u.Gt))&&(this.cbs.ondeclaration(this.sectionStart,this.index),this.state=r.Text,this.sectionStart=this.index+1);},s.prototype.stateInProcessingInstruction=function(c){(c===u.Gt||this.fastForwardTo(u.Gt))&&(this.cbs.onprocessinginstruction(this.sectionStart,this.index),this.state=r.Text,this.sectionStart=this.index+1);},s.prototype.stateBeforeComment=function(c){c===u.Dash?(this.state=r.InCommentLike,this.currentSequence=f.CommentEnd,this.sequenceIndex=2,this.sectionStart=this.index+1):this.state=r.InDeclaration;},s.prototype.stateInSpecialComment=function(c){(c===u.Gt||this.fastForwardTo(u.Gt))&&(this.cbs.oncomment(this.sectionStart,this.index,0),this.state=r.Text,this.sectionStart=this.index+1);},s.prototype.stateBeforeSpecialS=function(c){var x=c|32;x===f.ScriptEnd[3]?this.startSpecial(f.ScriptEnd,4):x===f.StyleEnd[3]?this.startSpecial(f.StyleEnd,4):(this.state=r.InTagName,this.stateInTagName(c));},s.prototype.stateBeforeEntity=function(c){this.entityExcess=1,this.entityResult=0,c===u.Number?this.state=r.BeforeNumericEntity:c===u.Amp||(this.trieIndex=0,this.trieCurrent=this.entityTrie[0],this.state=r.InNamedEntity,this.stateInNamedEntity(c));},s.prototype.stateInNamedEntity=function(c){if(this.entityExcess+=1,this.trieIndex=(0, e.determineBranch)(this.entityTrie,this.trieCurrent,this.trieIndex+1,c),this.trieIndex<0){this.emitNamedEntity(),this.index--;return}this.trieCurrent=this.entityTrie[this.trieIndex];var x=this.trieCurrent&e.BinTrieFlags.VALUE_LENGTH;if(x){var y=(x>>14)-1;if(!this.allowLegacyEntity()&&c!==u.Semi)this.trieIndex+=y;else {var v=this.index-this.entityExcess+1;v>this.sectionStart&&this.emitPartial(this.sectionStart,v),this.entityResult=this.trieIndex,this.trieIndex+=y,this.entityExcess=0,this.sectionStart=this.index+1,y===0&&this.emitNamedEntity();}}},s.prototype.emitNamedEntity=function(){if(this.state=this.baseState,this.entityResult!==0){var c=(this.entityTrie[this.entityResult]&e.BinTrieFlags.VALUE_LENGTH)>>14;switch(c){case 1:{this.emitCodePoint(this.entityTrie[this.entityResult]&~e.BinTrieFlags.VALUE_LENGTH);break}case 2:{this.emitCodePoint(this.entityTrie[this.entityResult+1]);break}case 3:this.emitCodePoint(this.entityTrie[this.entityResult+1]),this.emitCodePoint(this.entityTrie[this.entityResult+2]);}}},s.prototype.stateBeforeNumericEntity=function(c){(c|32)===u.LowerX?(this.entityExcess++,this.state=r.InHexEntity):(this.state=r.InNumericEntity,this.stateInNumericEntity(c));},s.prototype.emitNumericEntity=function(c){var x=this.index-this.entityExcess-1,y=x+2+ +(this.state===r.InHexEntity);y!==this.index&&(x>this.sectionStart&&this.emitPartial(this.sectionStart,x),this.sectionStart=this.index+Number(c),this.emitCodePoint((0, e.replaceCodePoint)(this.entityResult))),this.state=this.baseState;},s.prototype.stateInNumericEntity=function(c){c===u.Semi?this.emitNumericEntity(!0):i(c)?(this.entityResult=this.entityResult*10+(c-u.Zero),this.entityExcess++):(this.allowLegacyEntity()?this.emitNumericEntity(!1):this.state=this.baseState,this.index--);},s.prototype.stateInHexEntity=function(c){c===u.Semi?this.emitNumericEntity(!0):i(c)?(this.entityResult=this.entityResult*16+(c-u.Zero),this.entityExcess++):o(c)?(this.entityResult=this.entityResult*16+((c|32)-u.LowerA+10),this.entityExcess++):(this.allowLegacyEntity()?this.emitNumericEntity(!1):this.state=this.baseState,this.index--);},s.prototype.allowLegacyEntity=function(){return !this.xmlMode&&(this.baseState===r.Text||this.baseState===r.InSpecialTag)},s.prototype.cleanup=function(){this.running&&this.sectionStart!==this.index&&(this.state===r.Text||this.state===r.InSpecialTag&&this.sequenceIndex===0?(this.cbs.ontext(this.sectionStart,this.index),this.sectionStart=this.index):(this.state===r.InAttributeValueDq||this.state===r.InAttributeValueSq||this.state===r.InAttributeValueNq)&&(this.cbs.onattribdata(this.sectionStart,this.index),this.sectionStart=this.index));},s.prototype.shouldContinue=function(){return this.index<this.buffer.length+this.offset&&this.running},s.prototype.parse=function(){for(;this.shouldContinue();){var c=this.buffer.charCodeAt(this.index-this.offset);switch(this.state){case r.Text:{this.stateText(c);break}case r.SpecialStartSequence:{this.stateSpecialStartSequence(c);break}case r.InSpecialTag:{this.stateInSpecialTag(c);break}case r.CDATASequence:{this.stateCDATASequence(c);break}case r.InAttributeValueDq:{this.stateInAttributeValueDoubleQuotes(c);break}case r.InAttributeName:{this.stateInAttributeName(c);break}case r.InCommentLike:{this.stateInCommentLike(c);break}case r.InSpecialComment:{this.stateInSpecialComment(c);break}case r.BeforeAttributeName:{this.stateBeforeAttributeName(c);break}case r.InTagName:{this.stateInTagName(c);break}case r.InClosingTagName:{this.stateInClosingTagName(c);break}case r.BeforeTagName:{this.stateBeforeTagName(c);break}case r.AfterAttributeName:{this.stateAfterAttributeName(c);break}case r.InAttributeValueSq:{this.stateInAttributeValueSingleQuotes(c);break}case r.BeforeAttributeValue:{this.stateBeforeAttributeValue(c);break}case r.BeforeClosingTagName:{this.stateBeforeClosingTagName(c);break}case r.AfterClosingTagName:{this.stateAfterClosingTagName(c);break}case r.BeforeSpecialS:{this.stateBeforeSpecialS(c);break}case r.InAttributeValueNq:{this.stateInAttributeValueNoQuotes(c);break}case r.InSelfClosingTag:{this.stateInSelfClosingTag(c);break}case r.InDeclaration:{this.stateInDeclaration(c);break}case r.BeforeDeclaration:{this.stateBeforeDeclaration(c);break}case r.BeforeComment:{this.stateBeforeComment(c);break}case r.InProcessingInstruction:{this.stateInProcessingInstruction(c);break}case r.InNamedEntity:{this.stateInNamedEntity(c);break}case r.BeforeEntity:{this.stateBeforeEntity(c);break}case r.InHexEntity:{this.stateInHexEntity(c);break}case r.InNumericEntity:{this.stateInNumericEntity(c);break}default:this.stateBeforeNumericEntity(c);}this.index++;}this.cleanup();},s.prototype.finish=function(){this.state===r.InNamedEntity&&this.emitNamedEntity(),this.sectionStart<this.index&&this.handleTrailingData(),this.cbs.onend();},s.prototype.handleTrailingData=function(){var c=this.buffer.length+this.offset;this.state===r.InCommentLike?this.currentSequence===f.CdataEnd?this.cbs.oncdata(this.sectionStart,c,0):this.cbs.oncomment(this.sectionStart,c,0):this.state===r.InNumericEntity&&this.allowLegacyEntity()?this.emitNumericEntity(!1):this.state===r.InHexEntity&&this.allowLegacyEntity()?this.emitNumericEntity(!1):this.state===r.InTagName||this.state===r.BeforeAttributeName||this.state===r.BeforeAttributeValue||this.state===r.AfterAttributeName||this.state===r.InAttributeName||this.state===r.InAttributeValueSq||this.state===r.InAttributeValueDq||this.state===r.InAttributeValueNq||this.state===r.InClosingTagName||this.cbs.ontext(this.sectionStart,c);},s.prototype.emitPartial=function(c,x){this.baseState!==r.Text&&this.baseState!==r.InSpecialTag?this.cbs.onattribdata(c,x):this.cbs.ontext(c,x);},s.prototype.emitCodePoint=function(c){this.baseState!==r.Text&&this.baseState!==r.InSpecialTag?this.cbs.onattribentity(c):this.cbs.ontextentity(c);},s}();t.default=p;})(bu);var G0=qs&&qs.__createBinding||(Object.create?function(t,e,u,r){r===void 0&&(r=u);var n=Object.getOwnPropertyDescriptor(e,u);(!n||("get"in n?!e.__esModule:n.writable||n.configurable))&&(n={enumerable:!0,get:function(){return e[u]}}),Object.defineProperty(t,r,n);}:function(t,e,u,r){r===void 0&&(r=u),t[r]=e[u];}),Z0=qs&&qs.__setModuleDefault||(Object.create?function(t,e){Object.defineProperty(t,"default",{enumerable:!0,value:e});}:function(t,e){t.default=e;}),X0=qs&&qs.__importStar||function(t){if(t&&t.__esModule)return t;var e={};if(t!=null)for(var u in t)u!=="default"&&Object.prototype.hasOwnProperty.call(t,u)&&G0(e,t,u);return Z0(e,t),e};Object.defineProperty(Ee,"__esModule",{value:!0});Ee.Parser=void 0;var Ne=X0(bu),Lu=we$1,pe$1=new Set(["input","option","optgroup","select","button","datalist","textarea"]),O=new Set(["p"]),Ou=new Set(["thead","tbody"]),qu=new Set(["dd","dt"]),Ru=new Set(["rt","rp"]),Q0=new Map([["tr",new Set(["tr","th","td"])],["th",new Set(["th"])],["td",new Set(["thead","th","td"])],["body",new Set(["head","link","script"])],["li",new Set(["li"])],["p",O],["h1",O],["h2",O],["h3",O],["h4",O],["h5",O],["h6",O],["select",pe$1],["input",pe$1],["output",pe$1],["button",pe$1],["datalist",pe$1],["textarea",pe$1],["option",new Set(["option"])],["optgroup",new Set(["optgroup","option"])],["dd",qu],["dt",qu],["address",O],["article",O],["aside",O],["blockquote",O],["details",O],["div",O],["dl",O],["fieldset",O],["figcaption",O],["figure",O],["footer",O],["form",O],["header",O],["hr",O],["main",O],["nav",O],["ol",O],["pre",O],["section",O],["table",O],["ul",O],["rt",Ru],["rp",Ru],["tbody",Ou],["tfoot",Ou]]),W0=new Set(["area","base","basefont","br","col","command","embed","frame","hr","img","input","isindex","keygen","link","meta","param","source","track","wbr"]),Pu=new Set(["math","svg"]),Mu=new Set(["mi","mo","mn","ms","mtext","annotation-xml","foreignobject","desc","title"]),K0=/\s|\//,Y0=function(){function t(e,u){u===void 0&&(u={});var r,n,a,i,l;this.options=u,this.startIndex=0,this.endIndex=0,this.openTagStart=0,this.tagname="",this.attribname="",this.attribvalue="",this.attribs=null,this.stack=[],this.foreignContext=[],this.buffers=[],this.bufferOffset=0,this.writeIndex=0,this.ended=!1,this.cbs=e??{},this.lowerCaseTagNames=(r=u.lowerCaseTags)!==null&&r!==void 0?r:!u.xmlMode,this.lowerCaseAttributeNames=(n=u.lowerCaseAttributeNames)!==null&&n!==void 0?n:!u.xmlMode,this.tokenizer=new((a=u.Tokenizer)!==null&&a!==void 0?a:Ne.default)(this.options,this),(l=(i=this.cbs).onparserinit)===null||l===void 0||l.call(i,this);}return t.prototype.ontext=function(e,u){var r,n,a=this.getSlice(e,u);this.endIndex=u-1,(n=(r=this.cbs).ontext)===null||n===void 0||n.call(r,a),this.startIndex=u;},t.prototype.ontextentity=function(e){var u,r,n=this.tokenizer.getSectionStart();this.endIndex=n-1,(r=(u=this.cbs).ontext)===null||r===void 0||r.call(u,(0, Lu.fromCodePoint)(e)),this.startIndex=n;},t.prototype.isVoidElement=function(e){return !this.options.xmlMode&&W0.has(e)},t.prototype.onopentagname=function(e,u){this.endIndex=u;var r=this.getSlice(e,u);this.lowerCaseTagNames&&(r=r.toLowerCase()),this.emitOpenTag(r);},t.prototype.emitOpenTag=function(e){var u,r,n,a;this.openTagStart=this.startIndex,this.tagname=e;var i=!this.options.xmlMode&&Q0.get(e);if(i)for(;this.stack.length>0&&i.has(this.stack[this.stack.length-1]);){var l=this.stack.pop();(r=(u=this.cbs).onclosetag)===null||r===void 0||r.call(u,l,!0);}this.isVoidElement(e)||(this.stack.push(e),Pu.has(e)?this.foreignContext.push(!0):Mu.has(e)&&this.foreignContext.push(!1)),(a=(n=this.cbs).onopentagname)===null||a===void 0||a.call(n,e),this.cbs.onopentag&&(this.attribs={});},t.prototype.endOpenTag=function(e){var u,r;this.startIndex=this.openTagStart,this.attribs&&((r=(u=this.cbs).onopentag)===null||r===void 0||r.call(u,this.tagname,this.attribs,e),this.attribs=null),this.cbs.onclosetag&&this.isVoidElement(this.tagname)&&this.cbs.onclosetag(this.tagname,!0),this.tagname="";},t.prototype.onopentagend=function(e){this.endIndex=e,this.endOpenTag(!1),this.startIndex=e+1;},t.prototype.onclosetag=function(e,u){var r,n,a,i,l,o;this.endIndex=u;var d=this.getSlice(e,u);if(this.lowerCaseTagNames&&(d=d.toLowerCase()),(Pu.has(d)||Mu.has(d))&&this.foreignContext.pop(),this.isVoidElement(d))!this.options.xmlMode&&d==="br"&&((n=(r=this.cbs).onopentagname)===null||n===void 0||n.call(r,"br"),(i=(a=this.cbs).onopentag)===null||i===void 0||i.call(a,"br",{},!0),(o=(l=this.cbs).onclosetag)===null||o===void 0||o.call(l,"br",!1));else {var f=this.stack.lastIndexOf(d);if(f!==-1)if(this.cbs.onclosetag)for(var p=this.stack.length-f;p--;)this.cbs.onclosetag(this.stack.pop(),p!==0);else this.stack.length=f;else !this.options.xmlMode&&d==="p"&&(this.emitOpenTag("p"),this.closeCurrentTag(!0));}this.startIndex=u+1;},t.prototype.onselfclosingtag=function(e){this.endIndex=e,this.options.xmlMode||this.options.recognizeSelfClosing||this.foreignContext[this.foreignContext.length-1]?(this.closeCurrentTag(!1),this.startIndex=e+1):this.onopentagend(e);},t.prototype.closeCurrentTag=function(e){var u,r,n=this.tagname;this.endOpenTag(e),this.stack[this.stack.length-1]===n&&((r=(u=this.cbs).onclosetag)===null||r===void 0||r.call(u,n,!e),this.stack.pop());},t.prototype.onattribname=function(e,u){this.startIndex=e;var r=this.getSlice(e,u);this.attribname=this.lowerCaseAttributeNames?r.toLowerCase():r;},t.prototype.onattribdata=function(e,u){this.attribvalue+=this.getSlice(e,u);},t.prototype.onattribentity=function(e){this.attribvalue+=(0, Lu.fromCodePoint)(e);},t.prototype.onattribend=function(e,u){var r,n;this.endIndex=u,(n=(r=this.cbs).onattribute)===null||n===void 0||n.call(r,this.attribname,this.attribvalue,e===Ne.QuoteType.Double?'"':e===Ne.QuoteType.Single?"'":e===Ne.QuoteType.NoValue?void 0:null),this.attribs&&!Object.prototype.hasOwnProperty.call(this.attribs,this.attribname)&&(this.attribs[this.attribname]=this.attribvalue),this.attribvalue="";},t.prototype.getInstructionName=function(e){var u=e.search(K0),r=u<0?e:e.substr(0,u);return this.lowerCaseTagNames&&(r=r.toLowerCase()),r},t.prototype.ondeclaration=function(e,u){this.endIndex=u;var r=this.getSlice(e,u);if(this.cbs.onprocessinginstruction){var n=this.getInstructionName(r);this.cbs.onprocessinginstruction("!".concat(n),"!".concat(r));}this.startIndex=u+1;},t.prototype.onprocessinginstruction=function(e,u){this.endIndex=u;var r=this.getSlice(e,u);if(this.cbs.onprocessinginstruction){var n=this.getInstructionName(r);this.cbs.onprocessinginstruction("?".concat(n),"?".concat(r));}this.startIndex=u+1;},t.prototype.oncomment=function(e,u,r){var n,a,i,l;this.endIndex=u,(a=(n=this.cbs).oncomment)===null||a===void 0||a.call(n,this.getSlice(e,u-r)),(l=(i=this.cbs).oncommentend)===null||l===void 0||l.call(i),this.startIndex=u+1;},t.prototype.oncdata=function(e,u,r){var n,a,i,l,o,d,f,p,s,c;this.endIndex=u;var x=this.getSlice(e,u-r);this.options.xmlMode||this.options.recognizeCDATA?((a=(n=this.cbs).oncdatastart)===null||a===void 0||a.call(n),(l=(i=this.cbs).ontext)===null||l===void 0||l.call(i,x),(d=(o=this.cbs).oncdataend)===null||d===void 0||d.call(o)):((p=(f=this.cbs).oncomment)===null||p===void 0||p.call(f,"[CDATA[".concat(x,"]]")),(c=(s=this.cbs).oncommentend)===null||c===void 0||c.call(s)),this.startIndex=u+1;},t.prototype.onend=function(){var e,u;if(this.cbs.onclosetag){this.endIndex=this.startIndex;for(var r=this.stack.length;r>0;this.cbs.onclosetag(this.stack[--r],!0));}(u=(e=this.cbs).onend)===null||u===void 0||u.call(e);},t.prototype.reset=function(){var e,u,r,n;(u=(e=this.cbs).onreset)===null||u===void 0||u.call(e),this.tokenizer.reset(),this.tagname="",this.attribname="",this.attribs=null,this.stack.length=0,this.startIndex=0,this.endIndex=0,(n=(r=this.cbs).onparserinit)===null||n===void 0||n.call(r,this),this.buffers.length=0,this.bufferOffset=0,this.writeIndex=0,this.ended=!1;},t.prototype.parseComplete=function(e){this.reset(),this.end(e);},t.prototype.getSlice=function(e,u){for(;e-this.bufferOffset>=this.buffers[0].length;)this.shiftBuffer();for(var r=this.buffers[0].slice(e-this.bufferOffset,u-this.bufferOffset);u-this.bufferOffset>this.buffers[0].length;)this.shiftBuffer(),r+=this.buffers[0].slice(0,u-this.bufferOffset);return r},t.prototype.shiftBuffer=function(){this.bufferOffset+=this.buffers[0].length,this.writeIndex--,this.buffers.shift();},t.prototype.write=function(e){var u,r;if(this.ended){(r=(u=this.cbs).onerror)===null||r===void 0||r.call(u,new Error(".write() after done!"));return}this.buffers.push(e),this.tokenizer.running&&(this.tokenizer.write(e),this.writeIndex++);},t.prototype.end=function(e){var u,r;if(this.ended){(r=(u=this.cbs).onerror)===null||r===void 0||r.call(u,new Error(".end() after done!"));return}e&&this.write(e),this.ended=!0,this.tokenizer.end();},t.prototype.pause=function(){this.tokenizer.pause();},t.prototype.resume=function(){for(this.tokenizer.resume();this.tokenizer.running&&this.writeIndex<this.buffers.length;)this.tokenizer.write(this.buffers[this.writeIndex++]);this.ended&&this.tokenizer.end();},t.prototype.parseChunk=function(e){this.write(e);},t.prototype.done=function(e){this.end(e);},t}();Ee.Parser=Y0;var se$1={},De={};(function(t){Object.defineProperty(t,"__esModule",{value:!0}),t.Doctype=t.CDATA=t.Tag=t.Style=t.Script=t.Comment=t.Directive=t.Text=t.Root=t.isTag=t.ElementType=void 0;var e;(function(r){r.Root="root",r.Text="text",r.Directive="directive",r.Comment="comment",r.Script="script",r.Style="style",r.Tag="tag",r.CDATA="cdata",r.Doctype="doctype";})(e=t.ElementType||(t.ElementType={}));function u(r){return r.type===e.Tag||r.type===e.Script||r.type===e.Style}t.isTag=u,t.Root=e.Root,t.Text=e.Text,t.Directive=e.Directive,t.Comment=e.Comment,t.Script=e.Script,t.Style=e.Style,t.Tag=e.Tag,t.CDATA=e.CDATA,t.Doctype=e.Doctype;})(De);var B={},oe$1=qs&&qs.__extends||function(){var t=function(e,u){return t=Object.setPrototypeOf||{__proto__:[]}instanceof Array&&function(r,n){r.__proto__=n;}||function(r,n){for(var a in n)Object.prototype.hasOwnProperty.call(n,a)&&(r[a]=n[a]);},t(e,u)};return function(e,u){if(typeof u!="function"&&u!==null)throw new TypeError("Class extends value "+String(u)+" is not a constructor or null");t(e,u);function r(){this.constructor=e;}e.prototype=u===null?Object.create(u):(r.prototype=u.prototype,new r);}}(),ve$1=qs&&qs.__assign||function(){return ve$1=Object.assign||function(t){for(var e,u=1,r=arguments.length;u<r;u++){e=arguments[u];for(var n in e)Object.prototype.hasOwnProperty.call(e,n)&&(t[n]=e[n]);}return t},ve$1.apply(this,arguments)};Object.defineProperty(B,"__esModule",{value:!0});B.cloneNode=B.hasChildren=B.isDocument=B.isDirective=B.isComment=B.isText=B.isCDATA=B.isTag=B.Element=B.Document=B.CDATA=B.NodeWithChildren=B.ProcessingInstruction=B.Comment=B.Text=B.DataNode=B.Node=void 0;var X$2=De,mu=function(){function t(){this.parent=null,this.prev=null,this.next=null,this.startIndex=null,this.endIndex=null;}return Object.defineProperty(t.prototype,"parentNode",{get:function(){return this.parent},set:function(e){this.parent=e;},enumerable:!1,configurable:!0}),Object.defineProperty(t.prototype,"previousSibling",{get:function(){return this.prev},set:function(e){this.prev=e;},enumerable:!1,configurable:!0}),Object.defineProperty(t.prototype,"nextSibling",{get:function(){return this.next},set:function(e){this.next=e;},enumerable:!1,configurable:!0}),t.prototype.cloneNode=function(e){return e===void 0&&(e=!1),Du(this,e)},t}();B.Node=mu;var Ge=function(t){oe$1(e,t);function e(u){var r=t.call(this)||this;return r.data=u,r}return Object.defineProperty(e.prototype,"nodeValue",{get:function(){return this.data},set:function(u){this.data=u;},enumerable:!1,configurable:!0}),e}(mu);B.DataNode=Ge;var ft=function(t){oe$1(e,t);function e(){var u=t!==null&&t.apply(this,arguments)||this;return u.type=X$2.ElementType.Text,u}return Object.defineProperty(e.prototype,"nodeType",{get:function(){return 3},enumerable:!1,configurable:!0}),e}(Ge);B.Text=ft;var ht=function(t){oe$1(e,t);function e(){var u=t!==null&&t.apply(this,arguments)||this;return u.type=X$2.ElementType.Comment,u}return Object.defineProperty(e.prototype,"nodeType",{get:function(){return 8},enumerable:!1,configurable:!0}),e}(Ge);B.Comment=ht;var bt$2=function(t){oe$1(e,t);function e(u,r){var n=t.call(this,r)||this;return n.name=u,n.type=X$2.ElementType.Directive,n}return Object.defineProperty(e.prototype,"nodeType",{get:function(){return 1},enumerable:!1,configurable:!0}),e}(Ge);B.ProcessingInstruction=bt$2;var Ze=function(t){oe$1(e,t);function e(u){var r=t.call(this)||this;return r.children=u,r}return Object.defineProperty(e.prototype,"firstChild",{get:function(){var u;return (u=this.children[0])!==null&&u!==void 0?u:null},enumerable:!1,configurable:!0}),Object.defineProperty(e.prototype,"lastChild",{get:function(){return this.children.length>0?this.children[this.children.length-1]:null},enumerable:!1,configurable:!0}),Object.defineProperty(e.prototype,"childNodes",{get:function(){return this.children},set:function(u){this.children=u;},enumerable:!1,configurable:!0}),e}(mu);B.NodeWithChildren=Ze;var pt$1=function(t){oe$1(e,t);function e(){var u=t!==null&&t.apply(this,arguments)||this;return u.type=X$2.ElementType.CDATA,u}return Object.defineProperty(e.prototype,"nodeType",{get:function(){return 4},enumerable:!1,configurable:!0}),e}(Ze);B.CDATA=pt$1;var gt=function(t){oe$1(e,t);function e(){var u=t!==null&&t.apply(this,arguments)||this;return u.type=X$2.ElementType.Root,u}return Object.defineProperty(e.prototype,"nodeType",{get:function(){return 9},enumerable:!1,configurable:!0}),e}(Ze);B.Document=gt;var mt$1=function(t){oe$1(e,t);function e(u,r,n,a){n===void 0&&(n=[]),a===void 0&&(a=u==="script"?X$2.ElementType.Script:u==="style"?X$2.ElementType.Style:X$2.ElementType.Tag);var i=t.call(this,n)||this;return i.name=u,i.attribs=r,i.type=a,i}return Object.defineProperty(e.prototype,"nodeType",{get:function(){return 1},enumerable:!1,configurable:!0}),Object.defineProperty(e.prototype,"tagName",{get:function(){return this.name},set:function(u){this.name=u;},enumerable:!1,configurable:!0}),Object.defineProperty(e.prototype,"attributes",{get:function(){var u=this;return Object.keys(this.attribs).map(function(r){var n,a;return {name:r,value:u.attribs[r],namespace:(n=u["x-attribsNamespace"])===null||n===void 0?void 0:n[r],prefix:(a=u["x-attribsPrefix"])===null||a===void 0?void 0:a[r]}})},enumerable:!1,configurable:!0}),e}(Ze);B.Element=mt$1;function Dt$1(t){return (0, X$2.isTag)(t)}B.isTag=Dt$1;function xt$1(t){return t.type===X$2.ElementType.CDATA}B.isCDATA=xt$1;function At$1(t){return t.type===X$2.ElementType.Text}B.isText=At$1;function yt$2(t){return t.type===X$2.ElementType.Comment}B.isComment=yt$2;function vt$2(t){return t.type===X$2.ElementType.Directive}B.isDirective=vt$2;function Et$1(t){return t.type===X$2.ElementType.Root}B.isDocument=Et$1;function J0(t){return Object.prototype.hasOwnProperty.call(t,"children")}B.hasChildren=J0;function Du(t,e){e===void 0&&(e=!1);var u;if(At$1(t))u=new ft(t.data);else if(yt$2(t))u=new ht(t.data);else if(Dt$1(t)){var r=e?uu(t.children):[],n=new mt$1(t.name,ve$1({},t.attribs),r);r.forEach(function(o){return o.parent=n}),t.namespace!=null&&(n.namespace=t.namespace),t["x-attribsNamespace"]&&(n["x-attribsNamespace"]=ve$1({},t["x-attribsNamespace"])),t["x-attribsPrefix"]&&(n["x-attribsPrefix"]=ve$1({},t["x-attribsPrefix"])),u=n;}else if(xt$1(t)){var r=e?uu(t.children):[],a=new pt$1(r);r.forEach(function(d){return d.parent=a}),u=a;}else if(Et$1(t)){var r=e?uu(t.children):[],i=new gt(r);r.forEach(function(d){return d.parent=i}),t["x-mode"]&&(i["x-mode"]=t["x-mode"]),u=i;}else if(vt$2(t)){var l=new bt$2(t.name,t.data);t["x-name"]!=null&&(l["x-name"]=t["x-name"],l["x-publicId"]=t["x-publicId"],l["x-systemId"]=t["x-systemId"]),u=l;}else throw new Error("Not implemented yet: ".concat(t.type));return u.startIndex=t.startIndex,u.endIndex=t.endIndex,t.sourceCodeLocation!=null&&(u.sourceCodeLocation=t.sourceCodeLocation),u}B.cloneNode=Du;function uu(t){for(var e=t.map(function(r){return Du(r,!0)}),u=1;u<e.length;u++)e[u].prev=e[u-1],e[u-1].next=e[u];return e}(function(t){var e=qs&&qs.__createBinding||(Object.create?function(l,o,d,f){f===void 0&&(f=d);var p=Object.getOwnPropertyDescriptor(o,d);(!p||("get"in p?!o.__esModule:p.writable||p.configurable))&&(p={enumerable:!0,get:function(){return o[d]}}),Object.defineProperty(l,f,p);}:function(l,o,d,f){f===void 0&&(f=d),l[f]=o[d];}),u=qs&&qs.__exportStar||function(l,o){for(var d in l)d!=="default"&&!Object.prototype.hasOwnProperty.call(o,d)&&e(o,l,d);};Object.defineProperty(t,"__esModule",{value:!0}),t.DomHandler=void 0;var r=De,n=B;u(B,t);var a={withStartIndices:!1,withEndIndices:!1,xmlMode:!1},i=function(){function l(o,d,f){this.dom=[],this.root=new n.Document(this.dom),this.done=!1,this.tagStack=[this.root],this.lastNode=null,this.parser=null,typeof d=="function"&&(f=d,d=a),typeof o=="object"&&(d=o,o=void 0),this.callback=o??null,this.options=d??a,this.elementCB=f??null;}return l.prototype.onparserinit=function(o){this.parser=o;},l.prototype.onreset=function(){this.dom=[],this.root=new n.Document(this.dom),this.done=!1,this.tagStack=[this.root],this.lastNode=null,this.parser=null;},l.prototype.onend=function(){this.done||(this.done=!0,this.parser=null,this.handleCallback(null));},l.prototype.onerror=function(o){this.handleCallback(o);},l.prototype.onclosetag=function(){this.lastNode=null;var o=this.tagStack.pop();this.options.withEndIndices&&(o.endIndex=this.parser.endIndex),this.elementCB&&this.elementCB(o);},l.prototype.onopentag=function(o,d){var f=this.options.xmlMode?r.ElementType.Tag:void 0,p=new n.Element(o,d,void 0,f);this.addNode(p),this.tagStack.push(p);},l.prototype.ontext=function(o){var d=this.lastNode;if(d&&d.type===r.ElementType.Text)d.data+=o,this.options.withEndIndices&&(d.endIndex=this.parser.endIndex);else {var f=new n.Text(o);this.addNode(f),this.lastNode=f;}},l.prototype.oncomment=function(o){if(this.lastNode&&this.lastNode.type===r.ElementType.Comment){this.lastNode.data+=o;return}var d=new n.Comment(o);this.addNode(d),this.lastNode=d;},l.prototype.oncommentend=function(){this.lastNode=null;},l.prototype.oncdatastart=function(){var o=new n.Text(""),d=new n.CDATA([o]);this.addNode(d),o.parent=d,this.lastNode=o;},l.prototype.oncdataend=function(){this.lastNode=null;},l.prototype.onprocessinginstruction=function(o,d){var f=new n.ProcessingInstruction(o,d);this.addNode(f);},l.prototype.handleCallback=function(o){if(typeof this.callback=="function")this.callback(o,this.dom);else if(o)throw o},l.prototype.addNode=function(o){var d=this.tagStack[this.tagStack.length-1],f=d.children[d.children.length-1];this.options.withStartIndices&&(o.startIndex=this.parser.startIndex),this.options.withEndIndices&&(o.endIndex=this.parser.endIndex),d.children.push(o),f&&(o.prev=f,f.next=o),o.parent=d,this.lastNode=null;},l}();t.DomHandler=i,t.default=i;})(se$1);var qe$1={},K={},Te={},wt={},he$1={},xu={};Object.defineProperty(xu,"__esModule",{value:!0});function Le$2(t){for(var e=1;e<t.length;e++)t[e][0]+=t[e-1][0]+1;return t}xu.default=new Map(Le$2([[9,"&Tab;"],[0,"&NewLine;"],[22,"&excl;"],[0,"&quot;"],[0,"&num;"],[0,"&dollar;"],[0,"&percnt;"],[0,"&amp;"],[0,"&apos;"],[0,"&lpar;"],[0,"&rpar;"],[0,"&ast;"],[0,"&plus;"],[0,"&comma;"],[1,"&period;"],[0,"&sol;"],[10,"&colon;"],[0,"&semi;"],[0,{v:"&lt;",n:8402,o:"&nvlt;"}],[0,{v:"&equals;",n:8421,o:"&bne;"}],[0,{v:"&gt;",n:8402,o:"&nvgt;"}],[0,"&quest;"],[0,"&commat;"],[26,"&lbrack;"],[0,"&bsol;"],[0,"&rbrack;"],[0,"&Hat;"],[0,"&lowbar;"],[0,"&DiacriticalGrave;"],[5,{n:106,o:"&fjlig;"}],[20,"&lbrace;"],[0,"&verbar;"],[0,"&rbrace;"],[34,"&nbsp;"],[0,"&iexcl;"],[0,"&cent;"],[0,"&pound;"],[0,"&curren;"],[0,"&yen;"],[0,"&brvbar;"],[0,"&sect;"],[0,"&die;"],[0,"&copy;"],[0,"&ordf;"],[0,"&laquo;"],[0,"&not;"],[0,"&shy;"],[0,"&circledR;"],[0,"&macr;"],[0,"&deg;"],[0,"&PlusMinus;"],[0,"&sup2;"],[0,"&sup3;"],[0,"&acute;"],[0,"&micro;"],[0,"&para;"],[0,"&centerdot;"],[0,"&cedil;"],[0,"&sup1;"],[0,"&ordm;"],[0,"&raquo;"],[0,"&frac14;"],[0,"&frac12;"],[0,"&frac34;"],[0,"&iquest;"],[0,"&Agrave;"],[0,"&Aacute;"],[0,"&Acirc;"],[0,"&Atilde;"],[0,"&Auml;"],[0,"&angst;"],[0,"&AElig;"],[0,"&Ccedil;"],[0,"&Egrave;"],[0,"&Eacute;"],[0,"&Ecirc;"],[0,"&Euml;"],[0,"&Igrave;"],[0,"&Iacute;"],[0,"&Icirc;"],[0,"&Iuml;"],[0,"&ETH;"],[0,"&Ntilde;"],[0,"&Ograve;"],[0,"&Oacute;"],[0,"&Ocirc;"],[0,"&Otilde;"],[0,"&Ouml;"],[0,"&times;"],[0,"&Oslash;"],[0,"&Ugrave;"],[0,"&Uacute;"],[0,"&Ucirc;"],[0,"&Uuml;"],[0,"&Yacute;"],[0,"&THORN;"],[0,"&szlig;"],[0,"&agrave;"],[0,"&aacute;"],[0,"&acirc;"],[0,"&atilde;"],[0,"&auml;"],[0,"&aring;"],[0,"&aelig;"],[0,"&ccedil;"],[0,"&egrave;"],[0,"&eacute;"],[0,"&ecirc;"],[0,"&euml;"],[0,"&igrave;"],[0,"&iacute;"],[0,"&icirc;"],[0,"&iuml;"],[0,"&eth;"],[0,"&ntilde;"],[0,"&ograve;"],[0,"&oacute;"],[0,"&ocirc;"],[0,"&otilde;"],[0,"&ouml;"],[0,"&div;"],[0,"&oslash;"],[0,"&ugrave;"],[0,"&uacute;"],[0,"&ucirc;"],[0,"&uuml;"],[0,"&yacute;"],[0,"&thorn;"],[0,"&yuml;"],[0,"&Amacr;"],[0,"&amacr;"],[0,"&Abreve;"],[0,"&abreve;"],[0,"&Aogon;"],[0,"&aogon;"],[0,"&Cacute;"],[0,"&cacute;"],[0,"&Ccirc;"],[0,"&ccirc;"],[0,"&Cdot;"],[0,"&cdot;"],[0,"&Ccaron;"],[0,"&ccaron;"],[0,"&Dcaron;"],[0,"&dcaron;"],[0,"&Dstrok;"],[0,"&dstrok;"],[0,"&Emacr;"],[0,"&emacr;"],[2,"&Edot;"],[0,"&edot;"],[0,"&Eogon;"],[0,"&eogon;"],[0,"&Ecaron;"],[0,"&ecaron;"],[0,"&Gcirc;"],[0,"&gcirc;"],[0,"&Gbreve;"],[0,"&gbreve;"],[0,"&Gdot;"],[0,"&gdot;"],[0,"&Gcedil;"],[1,"&Hcirc;"],[0,"&hcirc;"],[0,"&Hstrok;"],[0,"&hstrok;"],[0,"&Itilde;"],[0,"&itilde;"],[0,"&Imacr;"],[0,"&imacr;"],[2,"&Iogon;"],[0,"&iogon;"],[0,"&Idot;"],[0,"&imath;"],[0,"&IJlig;"],[0,"&ijlig;"],[0,"&Jcirc;"],[0,"&jcirc;"],[0,"&Kcedil;"],[0,"&kcedil;"],[0,"&kgreen;"],[0,"&Lacute;"],[0,"&lacute;"],[0,"&Lcedil;"],[0,"&lcedil;"],[0,"&Lcaron;"],[0,"&lcaron;"],[0,"&Lmidot;"],[0,"&lmidot;"],[0,"&Lstrok;"],[0,"&lstrok;"],[0,"&Nacute;"],[0,"&nacute;"],[0,"&Ncedil;"],[0,"&ncedil;"],[0,"&Ncaron;"],[0,"&ncaron;"],[0,"&napos;"],[0,"&ENG;"],[0,"&eng;"],[0,"&Omacr;"],[0,"&omacr;"],[2,"&Odblac;"],[0,"&odblac;"],[0,"&OElig;"],[0,"&oelig;"],[0,"&Racute;"],[0,"&racute;"],[0,"&Rcedil;"],[0,"&rcedil;"],[0,"&Rcaron;"],[0,"&rcaron;"],[0,"&Sacute;"],[0,"&sacute;"],[0,"&Scirc;"],[0,"&scirc;"],[0,"&Scedil;"],[0,"&scedil;"],[0,"&Scaron;"],[0,"&scaron;"],[0,"&Tcedil;"],[0,"&tcedil;"],[0,"&Tcaron;"],[0,"&tcaron;"],[0,"&Tstrok;"],[0,"&tstrok;"],[0,"&Utilde;"],[0,"&utilde;"],[0,"&Umacr;"],[0,"&umacr;"],[0,"&Ubreve;"],[0,"&ubreve;"],[0,"&Uring;"],[0,"&uring;"],[0,"&Udblac;"],[0,"&udblac;"],[0,"&Uogon;"],[0,"&uogon;"],[0,"&Wcirc;"],[0,"&wcirc;"],[0,"&Ycirc;"],[0,"&ycirc;"],[0,"&Yuml;"],[0,"&Zacute;"],[0,"&zacute;"],[0,"&Zdot;"],[0,"&zdot;"],[0,"&Zcaron;"],[0,"&zcaron;"],[19,"&fnof;"],[34,"&imped;"],[63,"&gacute;"],[65,"&jmath;"],[142,"&circ;"],[0,"&caron;"],[16,"&breve;"],[0,"&DiacriticalDot;"],[0,"&ring;"],[0,"&ogon;"],[0,"&DiacriticalTilde;"],[0,"&dblac;"],[51,"&DownBreve;"],[127,"&Alpha;"],[0,"&Beta;"],[0,"&Gamma;"],[0,"&Delta;"],[0,"&Epsilon;"],[0,"&Zeta;"],[0,"&Eta;"],[0,"&Theta;"],[0,"&Iota;"],[0,"&Kappa;"],[0,"&Lambda;"],[0,"&Mu;"],[0,"&Nu;"],[0,"&Xi;"],[0,"&Omicron;"],[0,"&Pi;"],[0,"&Rho;"],[1,"&Sigma;"],[0,"&Tau;"],[0,"&Upsilon;"],[0,"&Phi;"],[0,"&Chi;"],[0,"&Psi;"],[0,"&ohm;"],[7,"&alpha;"],[0,"&beta;"],[0,"&gamma;"],[0,"&delta;"],[0,"&epsi;"],[0,"&zeta;"],[0,"&eta;"],[0,"&theta;"],[0,"&iota;"],[0,"&kappa;"],[0,"&lambda;"],[0,"&mu;"],[0,"&nu;"],[0,"&xi;"],[0,"&omicron;"],[0,"&pi;"],[0,"&rho;"],[0,"&sigmaf;"],[0,"&sigma;"],[0,"&tau;"],[0,"&upsi;"],[0,"&phi;"],[0,"&chi;"],[0,"&psi;"],[0,"&omega;"],[7,"&thetasym;"],[0,"&Upsi;"],[2,"&phiv;"],[0,"&piv;"],[5,"&Gammad;"],[0,"&digamma;"],[18,"&kappav;"],[0,"&rhov;"],[3,"&epsiv;"],[0,"&backepsilon;"],[10,"&IOcy;"],[0,"&DJcy;"],[0,"&GJcy;"],[0,"&Jukcy;"],[0,"&DScy;"],[0,"&Iukcy;"],[0,"&YIcy;"],[0,"&Jsercy;"],[0,"&LJcy;"],[0,"&NJcy;"],[0,"&TSHcy;"],[0,"&KJcy;"],[1,"&Ubrcy;"],[0,"&DZcy;"],[0,"&Acy;"],[0,"&Bcy;"],[0,"&Vcy;"],[0,"&Gcy;"],[0,"&Dcy;"],[0,"&IEcy;"],[0,"&ZHcy;"],[0,"&Zcy;"],[0,"&Icy;"],[0,"&Jcy;"],[0,"&Kcy;"],[0,"&Lcy;"],[0,"&Mcy;"],[0,"&Ncy;"],[0,"&Ocy;"],[0,"&Pcy;"],[0,"&Rcy;"],[0,"&Scy;"],[0,"&Tcy;"],[0,"&Ucy;"],[0,"&Fcy;"],[0,"&KHcy;"],[0,"&TScy;"],[0,"&CHcy;"],[0,"&SHcy;"],[0,"&SHCHcy;"],[0,"&HARDcy;"],[0,"&Ycy;"],[0,"&SOFTcy;"],[0,"&Ecy;"],[0,"&YUcy;"],[0,"&YAcy;"],[0,"&acy;"],[0,"&bcy;"],[0,"&vcy;"],[0,"&gcy;"],[0,"&dcy;"],[0,"&iecy;"],[0,"&zhcy;"],[0,"&zcy;"],[0,"&icy;"],[0,"&jcy;"],[0,"&kcy;"],[0,"&lcy;"],[0,"&mcy;"],[0,"&ncy;"],[0,"&ocy;"],[0,"&pcy;"],[0,"&rcy;"],[0,"&scy;"],[0,"&tcy;"],[0,"&ucy;"],[0,"&fcy;"],[0,"&khcy;"],[0,"&tscy;"],[0,"&chcy;"],[0,"&shcy;"],[0,"&shchcy;"],[0,"&hardcy;"],[0,"&ycy;"],[0,"&softcy;"],[0,"&ecy;"],[0,"&yucy;"],[0,"&yacy;"],[1,"&iocy;"],[0,"&djcy;"],[0,"&gjcy;"],[0,"&jukcy;"],[0,"&dscy;"],[0,"&iukcy;"],[0,"&yicy;"],[0,"&jsercy;"],[0,"&ljcy;"],[0,"&njcy;"],[0,"&tshcy;"],[0,"&kjcy;"],[1,"&ubrcy;"],[0,"&dzcy;"],[7074,"&ensp;"],[0,"&emsp;"],[0,"&emsp13;"],[0,"&emsp14;"],[1,"&numsp;"],[0,"&puncsp;"],[0,"&ThinSpace;"],[0,"&hairsp;"],[0,"&NegativeMediumSpace;"],[0,"&zwnj;"],[0,"&zwj;"],[0,"&lrm;"],[0,"&rlm;"],[0,"&dash;"],[2,"&ndash;"],[0,"&mdash;"],[0,"&horbar;"],[0,"&Verbar;"],[1,"&lsquo;"],[0,"&CloseCurlyQuote;"],[0,"&lsquor;"],[1,"&ldquo;"],[0,"&CloseCurlyDoubleQuote;"],[0,"&bdquo;"],[1,"&dagger;"],[0,"&Dagger;"],[0,"&bull;"],[2,"&nldr;"],[0,"&hellip;"],[9,"&permil;"],[0,"&pertenk;"],[0,"&prime;"],[0,"&Prime;"],[0,"&tprime;"],[0,"&backprime;"],[3,"&lsaquo;"],[0,"&rsaquo;"],[3,"&oline;"],[2,"&caret;"],[1,"&hybull;"],[0,"&frasl;"],[10,"&bsemi;"],[7,"&qprime;"],[7,{v:"&MediumSpace;",n:8202,o:"&ThickSpace;"}],[0,"&NoBreak;"],[0,"&af;"],[0,"&InvisibleTimes;"],[0,"&ic;"],[72,"&euro;"],[46,"&tdot;"],[0,"&DotDot;"],[37,"&complexes;"],[2,"&incare;"],[4,"&gscr;"],[0,"&hamilt;"],[0,"&Hfr;"],[0,"&Hopf;"],[0,"&planckh;"],[0,"&hbar;"],[0,"&imagline;"],[0,"&Ifr;"],[0,"&lagran;"],[0,"&ell;"],[1,"&naturals;"],[0,"&numero;"],[0,"&copysr;"],[0,"&weierp;"],[0,"&Popf;"],[0,"&Qopf;"],[0,"&realine;"],[0,"&real;"],[0,"&reals;"],[0,"&rx;"],[3,"&trade;"],[1,"&integers;"],[2,"&mho;"],[0,"&zeetrf;"],[0,"&iiota;"],[2,"&bernou;"],[0,"&Cayleys;"],[1,"&escr;"],[0,"&Escr;"],[0,"&Fouriertrf;"],[1,"&Mellintrf;"],[0,"&order;"],[0,"&alefsym;"],[0,"&beth;"],[0,"&gimel;"],[0,"&daleth;"],[12,"&CapitalDifferentialD;"],[0,"&dd;"],[0,"&ee;"],[0,"&ii;"],[10,"&frac13;"],[0,"&frac23;"],[0,"&frac15;"],[0,"&frac25;"],[0,"&frac35;"],[0,"&frac45;"],[0,"&frac16;"],[0,"&frac56;"],[0,"&frac18;"],[0,"&frac38;"],[0,"&frac58;"],[0,"&frac78;"],[49,"&larr;"],[0,"&ShortUpArrow;"],[0,"&rarr;"],[0,"&darr;"],[0,"&harr;"],[0,"&updownarrow;"],[0,"&nwarr;"],[0,"&nearr;"],[0,"&LowerRightArrow;"],[0,"&LowerLeftArrow;"],[0,"&nlarr;"],[0,"&nrarr;"],[1,{v:"&rarrw;",n:824,o:"&nrarrw;"}],[0,"&Larr;"],[0,"&Uarr;"],[0,"&Rarr;"],[0,"&Darr;"],[0,"&larrtl;"],[0,"&rarrtl;"],[0,"&LeftTeeArrow;"],[0,"&mapstoup;"],[0,"&map;"],[0,"&DownTeeArrow;"],[1,"&hookleftarrow;"],[0,"&hookrightarrow;"],[0,"&larrlp;"],[0,"&looparrowright;"],[0,"&harrw;"],[0,"&nharr;"],[1,"&lsh;"],[0,"&rsh;"],[0,"&ldsh;"],[0,"&rdsh;"],[1,"&crarr;"],[0,"&cularr;"],[0,"&curarr;"],[2,"&circlearrowleft;"],[0,"&circlearrowright;"],[0,"&leftharpoonup;"],[0,"&DownLeftVector;"],[0,"&RightUpVector;"],[0,"&LeftUpVector;"],[0,"&rharu;"],[0,"&DownRightVector;"],[0,"&dharr;"],[0,"&dharl;"],[0,"&RightArrowLeftArrow;"],[0,"&udarr;"],[0,"&LeftArrowRightArrow;"],[0,"&leftleftarrows;"],[0,"&upuparrows;"],[0,"&rightrightarrows;"],[0,"&ddarr;"],[0,"&leftrightharpoons;"],[0,"&Equilibrium;"],[0,"&nlArr;"],[0,"&nhArr;"],[0,"&nrArr;"],[0,"&DoubleLeftArrow;"],[0,"&DoubleUpArrow;"],[0,"&DoubleRightArrow;"],[0,"&dArr;"],[0,"&DoubleLeftRightArrow;"],[0,"&DoubleUpDownArrow;"],[0,"&nwArr;"],[0,"&neArr;"],[0,"&seArr;"],[0,"&swArr;"],[0,"&lAarr;"],[0,"&rAarr;"],[1,"&zigrarr;"],[6,"&larrb;"],[0,"&rarrb;"],[15,"&DownArrowUpArrow;"],[7,"&loarr;"],[0,"&roarr;"],[0,"&hoarr;"],[0,"&forall;"],[0,"&comp;"],[0,{v:"&part;",n:824,o:"&npart;"}],[0,"&exist;"],[0,"&nexist;"],[0,"&empty;"],[1,"&Del;"],[0,"&Element;"],[0,"&NotElement;"],[1,"&ni;"],[0,"&notni;"],[2,"&prod;"],[0,"&coprod;"],[0,"&sum;"],[0,"&minus;"],[0,"&MinusPlus;"],[0,"&dotplus;"],[1,"&Backslash;"],[0,"&lowast;"],[0,"&compfn;"],[1,"&radic;"],[2,"&prop;"],[0,"&infin;"],[0,"&angrt;"],[0,{v:"&ang;",n:8402,o:"&nang;"}],[0,"&angmsd;"],[0,"&angsph;"],[0,"&mid;"],[0,"&nmid;"],[0,"&DoubleVerticalBar;"],[0,"&NotDoubleVerticalBar;"],[0,"&and;"],[0,"&or;"],[0,{v:"&cap;",n:65024,o:"&caps;"}],[0,{v:"&cup;",n:65024,o:"&cups;"}],[0,"&int;"],[0,"&Int;"],[0,"&iiint;"],[0,"&conint;"],[0,"&Conint;"],[0,"&Cconint;"],[0,"&cwint;"],[0,"&ClockwiseContourIntegral;"],[0,"&awconint;"],[0,"&there4;"],[0,"&becaus;"],[0,"&ratio;"],[0,"&Colon;"],[0,"&dotminus;"],[1,"&mDDot;"],[0,"&homtht;"],[0,{v:"&sim;",n:8402,o:"&nvsim;"}],[0,{v:"&backsim;",n:817,o:"&race;"}],[0,{v:"&ac;",n:819,o:"&acE;"}],[0,"&acd;"],[0,"&VerticalTilde;"],[0,"&NotTilde;"],[0,{v:"&eqsim;",n:824,o:"&nesim;"}],[0,"&sime;"],[0,"&NotTildeEqual;"],[0,"&cong;"],[0,"&simne;"],[0,"&ncong;"],[0,"&ap;"],[0,"&nap;"],[0,"&ape;"],[0,{v:"&apid;",n:824,o:"&napid;"}],[0,"&backcong;"],[0,{v:"&asympeq;",n:8402,o:"&nvap;"}],[0,{v:"&bump;",n:824,o:"&nbump;"}],[0,{v:"&bumpe;",n:824,o:"&nbumpe;"}],[0,{v:"&doteq;",n:824,o:"&nedot;"}],[0,"&doteqdot;"],[0,"&efDot;"],[0,"&erDot;"],[0,"&Assign;"],[0,"&ecolon;"],[0,"&ecir;"],[0,"&circeq;"],[1,"&wedgeq;"],[0,"&veeeq;"],[1,"&triangleq;"],[2,"&equest;"],[0,"&ne;"],[0,{v:"&Congruent;",n:8421,o:"&bnequiv;"}],[0,"&nequiv;"],[1,{v:"&le;",n:8402,o:"&nvle;"}],[0,{v:"&ge;",n:8402,o:"&nvge;"}],[0,{v:"&lE;",n:824,o:"&nlE;"}],[0,{v:"&gE;",n:824,o:"&ngE;"}],[0,{v:"&lnE;",n:65024,o:"&lvertneqq;"}],[0,{v:"&gnE;",n:65024,o:"&gvertneqq;"}],[0,{v:"&ll;",n:new Map(Le$2([[824,"&nLtv;"],[7577,"&nLt;"]]))}],[0,{v:"&gg;",n:new Map(Le$2([[824,"&nGtv;"],[7577,"&nGt;"]]))}],[0,"&between;"],[0,"&NotCupCap;"],[0,"&nless;"],[0,"&ngt;"],[0,"&nle;"],[0,"&nge;"],[0,"&lesssim;"],[0,"&GreaterTilde;"],[0,"&nlsim;"],[0,"&ngsim;"],[0,"&LessGreater;"],[0,"&gl;"],[0,"&NotLessGreater;"],[0,"&NotGreaterLess;"],[0,"&pr;"],[0,"&sc;"],[0,"&prcue;"],[0,"&sccue;"],[0,"&PrecedesTilde;"],[0,{v:"&scsim;",n:824,o:"&NotSucceedsTilde;"}],[0,"&NotPrecedes;"],[0,"&NotSucceeds;"],[0,{v:"&sub;",n:8402,o:"&NotSubset;"}],[0,{v:"&sup;",n:8402,o:"&NotSuperset;"}],[0,"&nsub;"],[0,"&nsup;"],[0,"&sube;"],[0,"&supe;"],[0,"&NotSubsetEqual;"],[0,"&NotSupersetEqual;"],[0,{v:"&subne;",n:65024,o:"&varsubsetneq;"}],[0,{v:"&supne;",n:65024,o:"&varsupsetneq;"}],[1,"&cupdot;"],[0,"&UnionPlus;"],[0,{v:"&sqsub;",n:824,o:"&NotSquareSubset;"}],[0,{v:"&sqsup;",n:824,o:"&NotSquareSuperset;"}],[0,"&sqsube;"],[0,"&sqsupe;"],[0,{v:"&sqcap;",n:65024,o:"&sqcaps;"}],[0,{v:"&sqcup;",n:65024,o:"&sqcups;"}],[0,"&CirclePlus;"],[0,"&CircleMinus;"],[0,"&CircleTimes;"],[0,"&osol;"],[0,"&CircleDot;"],[0,"&circledcirc;"],[0,"&circledast;"],[1,"&circleddash;"],[0,"&boxplus;"],[0,"&boxminus;"],[0,"&boxtimes;"],[0,"&dotsquare;"],[0,"&RightTee;"],[0,"&dashv;"],[0,"&DownTee;"],[0,"&bot;"],[1,"&models;"],[0,"&DoubleRightTee;"],[0,"&Vdash;"],[0,"&Vvdash;"],[0,"&VDash;"],[0,"&nvdash;"],[0,"&nvDash;"],[0,"&nVdash;"],[0,"&nVDash;"],[0,"&prurel;"],[1,"&LeftTriangle;"],[0,"&RightTriangle;"],[0,{v:"&LeftTriangleEqual;",n:8402,o:"&nvltrie;"}],[0,{v:"&RightTriangleEqual;",n:8402,o:"&nvrtrie;"}],[0,"&origof;"],[0,"&imof;"],[0,"&multimap;"],[0,"&hercon;"],[0,"&intcal;"],[0,"&veebar;"],[1,"&barvee;"],[0,"&angrtvb;"],[0,"&lrtri;"],[0,"&bigwedge;"],[0,"&bigvee;"],[0,"&bigcap;"],[0,"&bigcup;"],[0,"&diam;"],[0,"&sdot;"],[0,"&sstarf;"],[0,"&divideontimes;"],[0,"&bowtie;"],[0,"&ltimes;"],[0,"&rtimes;"],[0,"&leftthreetimes;"],[0,"&rightthreetimes;"],[0,"&backsimeq;"],[0,"&curlyvee;"],[0,"&curlywedge;"],[0,"&Sub;"],[0,"&Sup;"],[0,"&Cap;"],[0,"&Cup;"],[0,"&fork;"],[0,"&epar;"],[0,"&lessdot;"],[0,"&gtdot;"],[0,{v:"&Ll;",n:824,o:"&nLl;"}],[0,{v:"&Gg;",n:824,o:"&nGg;"}],[0,{v:"&leg;",n:65024,o:"&lesg;"}],[0,{v:"&gel;",n:65024,o:"&gesl;"}],[2,"&cuepr;"],[0,"&cuesc;"],[0,"&NotPrecedesSlantEqual;"],[0,"&NotSucceedsSlantEqual;"],[0,"&NotSquareSubsetEqual;"],[0,"&NotSquareSupersetEqual;"],[2,"&lnsim;"],[0,"&gnsim;"],[0,"&precnsim;"],[0,"&scnsim;"],[0,"&nltri;"],[0,"&NotRightTriangle;"],[0,"&nltrie;"],[0,"&NotRightTriangleEqual;"],[0,"&vellip;"],[0,"&ctdot;"],[0,"&utdot;"],[0,"&dtdot;"],[0,"&disin;"],[0,"&isinsv;"],[0,"&isins;"],[0,{v:"&isindot;",n:824,o:"&notindot;"}],[0,"&notinvc;"],[0,"&notinvb;"],[1,{v:"&isinE;",n:824,o:"&notinE;"}],[0,"&nisd;"],[0,"&xnis;"],[0,"&nis;"],[0,"&notnivc;"],[0,"&notnivb;"],[6,"&barwed;"],[0,"&Barwed;"],[1,"&lceil;"],[0,"&rceil;"],[0,"&LeftFloor;"],[0,"&rfloor;"],[0,"&drcrop;"],[0,"&dlcrop;"],[0,"&urcrop;"],[0,"&ulcrop;"],[0,"&bnot;"],[1,"&profline;"],[0,"&profsurf;"],[1,"&telrec;"],[0,"&target;"],[5,"&ulcorn;"],[0,"&urcorn;"],[0,"&dlcorn;"],[0,"&drcorn;"],[2,"&frown;"],[0,"&smile;"],[9,"&cylcty;"],[0,"&profalar;"],[7,"&topbot;"],[6,"&ovbar;"],[1,"&solbar;"],[60,"&angzarr;"],[51,"&lmoustache;"],[0,"&rmoustache;"],[2,"&OverBracket;"],[0,"&bbrk;"],[0,"&bbrktbrk;"],[37,"&OverParenthesis;"],[0,"&UnderParenthesis;"],[0,"&OverBrace;"],[0,"&UnderBrace;"],[2,"&trpezium;"],[4,"&elinters;"],[59,"&blank;"],[164,"&circledS;"],[55,"&boxh;"],[1,"&boxv;"],[9,"&boxdr;"],[3,"&boxdl;"],[3,"&boxur;"],[3,"&boxul;"],[3,"&boxvr;"],[7,"&boxvl;"],[7,"&boxhd;"],[7,"&boxhu;"],[7,"&boxvh;"],[19,"&boxH;"],[0,"&boxV;"],[0,"&boxdR;"],[0,"&boxDr;"],[0,"&boxDR;"],[0,"&boxdL;"],[0,"&boxDl;"],[0,"&boxDL;"],[0,"&boxuR;"],[0,"&boxUr;"],[0,"&boxUR;"],[0,"&boxuL;"],[0,"&boxUl;"],[0,"&boxUL;"],[0,"&boxvR;"],[0,"&boxVr;"],[0,"&boxVR;"],[0,"&boxvL;"],[0,"&boxVl;"],[0,"&boxVL;"],[0,"&boxHd;"],[0,"&boxhD;"],[0,"&boxHD;"],[0,"&boxHu;"],[0,"&boxhU;"],[0,"&boxHU;"],[0,"&boxvH;"],[0,"&boxVh;"],[0,"&boxVH;"],[19,"&uhblk;"],[3,"&lhblk;"],[3,"&block;"],[8,"&blk14;"],[0,"&blk12;"],[0,"&blk34;"],[13,"&square;"],[8,"&blacksquare;"],[0,"&EmptyVerySmallSquare;"],[1,"&rect;"],[0,"&marker;"],[2,"&fltns;"],[1,"&bigtriangleup;"],[0,"&blacktriangle;"],[0,"&triangle;"],[2,"&blacktriangleright;"],[0,"&rtri;"],[3,"&bigtriangledown;"],[0,"&blacktriangledown;"],[0,"&dtri;"],[2,"&blacktriangleleft;"],[0,"&ltri;"],[6,"&loz;"],[0,"&cir;"],[32,"&tridot;"],[2,"&bigcirc;"],[8,"&ultri;"],[0,"&urtri;"],[0,"&lltri;"],[0,"&EmptySmallSquare;"],[0,"&FilledSmallSquare;"],[8,"&bigstar;"],[0,"&star;"],[7,"&phone;"],[49,"&female;"],[1,"&male;"],[29,"&spades;"],[2,"&clubs;"],[1,"&hearts;"],[0,"&diamondsuit;"],[3,"&sung;"],[2,"&flat;"],[0,"&natural;"],[0,"&sharp;"],[163,"&check;"],[3,"&cross;"],[8,"&malt;"],[21,"&sext;"],[33,"&VerticalSeparator;"],[25,"&lbbrk;"],[0,"&rbbrk;"],[84,"&bsolhsub;"],[0,"&suphsol;"],[28,"&LeftDoubleBracket;"],[0,"&RightDoubleBracket;"],[0,"&lang;"],[0,"&rang;"],[0,"&Lang;"],[0,"&Rang;"],[0,"&loang;"],[0,"&roang;"],[7,"&longleftarrow;"],[0,"&longrightarrow;"],[0,"&longleftrightarrow;"],[0,"&DoubleLongLeftArrow;"],[0,"&DoubleLongRightArrow;"],[0,"&DoubleLongLeftRightArrow;"],[1,"&longmapsto;"],[2,"&dzigrarr;"],[258,"&nvlArr;"],[0,"&nvrArr;"],[0,"&nvHarr;"],[0,"&Map;"],[6,"&lbarr;"],[0,"&bkarow;"],[0,"&lBarr;"],[0,"&dbkarow;"],[0,"&drbkarow;"],[0,"&DDotrahd;"],[0,"&UpArrowBar;"],[0,"&DownArrowBar;"],[2,"&Rarrtl;"],[2,"&latail;"],[0,"&ratail;"],[0,"&lAtail;"],[0,"&rAtail;"],[0,"&larrfs;"],[0,"&rarrfs;"],[0,"&larrbfs;"],[0,"&rarrbfs;"],[2,"&nwarhk;"],[0,"&nearhk;"],[0,"&hksearow;"],[0,"&hkswarow;"],[0,"&nwnear;"],[0,"&nesear;"],[0,"&seswar;"],[0,"&swnwar;"],[8,{v:"&rarrc;",n:824,o:"&nrarrc;"}],[1,"&cudarrr;"],[0,"&ldca;"],[0,"&rdca;"],[0,"&cudarrl;"],[0,"&larrpl;"],[2,"&curarrm;"],[0,"&cularrp;"],[7,"&rarrpl;"],[2,"&harrcir;"],[0,"&Uarrocir;"],[0,"&lurdshar;"],[0,"&ldrushar;"],[2,"&LeftRightVector;"],[0,"&RightUpDownVector;"],[0,"&DownLeftRightVector;"],[0,"&LeftUpDownVector;"],[0,"&LeftVectorBar;"],[0,"&RightVectorBar;"],[0,"&RightUpVectorBar;"],[0,"&RightDownVectorBar;"],[0,"&DownLeftVectorBar;"],[0,"&DownRightVectorBar;"],[0,"&LeftUpVectorBar;"],[0,"&LeftDownVectorBar;"],[0,"&LeftTeeVector;"],[0,"&RightTeeVector;"],[0,"&RightUpTeeVector;"],[0,"&RightDownTeeVector;"],[0,"&DownLeftTeeVector;"],[0,"&DownRightTeeVector;"],[0,"&LeftUpTeeVector;"],[0,"&LeftDownTeeVector;"],[0,"&lHar;"],[0,"&uHar;"],[0,"&rHar;"],[0,"&dHar;"],[0,"&luruhar;"],[0,"&ldrdhar;"],[0,"&ruluhar;"],[0,"&rdldhar;"],[0,"&lharul;"],[0,"&llhard;"],[0,"&rharul;"],[0,"&lrhard;"],[0,"&udhar;"],[0,"&duhar;"],[0,"&RoundImplies;"],[0,"&erarr;"],[0,"&simrarr;"],[0,"&larrsim;"],[0,"&rarrsim;"],[0,"&rarrap;"],[0,"&ltlarr;"],[1,"&gtrarr;"],[0,"&subrarr;"],[1,"&suplarr;"],[0,"&lfisht;"],[0,"&rfisht;"],[0,"&ufisht;"],[0,"&dfisht;"],[5,"&lopar;"],[0,"&ropar;"],[4,"&lbrke;"],[0,"&rbrke;"],[0,"&lbrkslu;"],[0,"&rbrksld;"],[0,"&lbrksld;"],[0,"&rbrkslu;"],[0,"&langd;"],[0,"&rangd;"],[0,"&lparlt;"],[0,"&rpargt;"],[0,"&gtlPar;"],[0,"&ltrPar;"],[3,"&vzigzag;"],[1,"&vangrt;"],[0,"&angrtvbd;"],[6,"&ange;"],[0,"&range;"],[0,"&dwangle;"],[0,"&uwangle;"],[0,"&angmsdaa;"],[0,"&angmsdab;"],[0,"&angmsdac;"],[0,"&angmsdad;"],[0,"&angmsdae;"],[0,"&angmsdaf;"],[0,"&angmsdag;"],[0,"&angmsdah;"],[0,"&bemptyv;"],[0,"&demptyv;"],[0,"&cemptyv;"],[0,"&raemptyv;"],[0,"&laemptyv;"],[0,"&ohbar;"],[0,"&omid;"],[0,"&opar;"],[1,"&operp;"],[1,"&olcross;"],[0,"&odsold;"],[1,"&olcir;"],[0,"&ofcir;"],[0,"&olt;"],[0,"&ogt;"],[0,"&cirscir;"],[0,"&cirE;"],[0,"&solb;"],[0,"&bsolb;"],[3,"&boxbox;"],[3,"&trisb;"],[0,"&rtriltri;"],[0,{v:"&LeftTriangleBar;",n:824,o:"&NotLeftTriangleBar;"}],[0,{v:"&RightTriangleBar;",n:824,o:"&NotRightTriangleBar;"}],[11,"&iinfin;"],[0,"&infintie;"],[0,"&nvinfin;"],[4,"&eparsl;"],[0,"&smeparsl;"],[0,"&eqvparsl;"],[5,"&blacklozenge;"],[8,"&RuleDelayed;"],[1,"&dsol;"],[9,"&bigodot;"],[0,"&bigoplus;"],[0,"&bigotimes;"],[1,"&biguplus;"],[1,"&bigsqcup;"],[5,"&iiiint;"],[0,"&fpartint;"],[2,"&cirfnint;"],[0,"&awint;"],[0,"&rppolint;"],[0,"&scpolint;"],[0,"&npolint;"],[0,"&pointint;"],[0,"&quatint;"],[0,"&intlarhk;"],[10,"&pluscir;"],[0,"&plusacir;"],[0,"&simplus;"],[0,"&plusdu;"],[0,"&plussim;"],[0,"&plustwo;"],[1,"&mcomma;"],[0,"&minusdu;"],[2,"&loplus;"],[0,"&roplus;"],[0,"&Cross;"],[0,"&timesd;"],[0,"&timesbar;"],[1,"&smashp;"],[0,"&lotimes;"],[0,"&rotimes;"],[0,"&otimesas;"],[0,"&Otimes;"],[0,"&odiv;"],[0,"&triplus;"],[0,"&triminus;"],[0,"&tritime;"],[0,"&intprod;"],[2,"&amalg;"],[0,"&capdot;"],[1,"&ncup;"],[0,"&ncap;"],[0,"&capand;"],[0,"&cupor;"],[0,"&cupcap;"],[0,"&capcup;"],[0,"&cupbrcap;"],[0,"&capbrcup;"],[0,"&cupcup;"],[0,"&capcap;"],[0,"&ccups;"],[0,"&ccaps;"],[2,"&ccupssm;"],[2,"&And;"],[0,"&Or;"],[0,"&andand;"],[0,"&oror;"],[0,"&orslope;"],[0,"&andslope;"],[1,"&andv;"],[0,"&orv;"],[0,"&andd;"],[0,"&ord;"],[1,"&wedbar;"],[6,"&sdote;"],[3,"&simdot;"],[2,{v:"&congdot;",n:824,o:"&ncongdot;"}],[0,"&easter;"],[0,"&apacir;"],[0,{v:"&apE;",n:824,o:"&napE;"}],[0,"&eplus;"],[0,"&pluse;"],[0,"&Esim;"],[0,"&Colone;"],[0,"&Equal;"],[1,"&ddotseq;"],[0,"&equivDD;"],[0,"&ltcir;"],[0,"&gtcir;"],[0,"&ltquest;"],[0,"&gtquest;"],[0,{v:"&leqslant;",n:824,o:"&nleqslant;"}],[0,{v:"&geqslant;",n:824,o:"&ngeqslant;"}],[0,"&lesdot;"],[0,"&gesdot;"],[0,"&lesdoto;"],[0,"&gesdoto;"],[0,"&lesdotor;"],[0,"&gesdotol;"],[0,"&lap;"],[0,"&gap;"],[0,"&lne;"],[0,"&gne;"],[0,"&lnap;"],[0,"&gnap;"],[0,"&lEg;"],[0,"&gEl;"],[0,"&lsime;"],[0,"&gsime;"],[0,"&lsimg;"],[0,"&gsiml;"],[0,"&lgE;"],[0,"&glE;"],[0,"&lesges;"],[0,"&gesles;"],[0,"&els;"],[0,"&egs;"],[0,"&elsdot;"],[0,"&egsdot;"],[0,"&el;"],[0,"&eg;"],[2,"&siml;"],[0,"&simg;"],[0,"&simlE;"],[0,"&simgE;"],[0,{v:"&LessLess;",n:824,o:"&NotNestedLessLess;"}],[0,{v:"&GreaterGreater;",n:824,o:"&NotNestedGreaterGreater;"}],[1,"&glj;"],[0,"&gla;"],[0,"&ltcc;"],[0,"&gtcc;"],[0,"&lescc;"],[0,"&gescc;"],[0,"&smt;"],[0,"&lat;"],[0,{v:"&smte;",n:65024,o:"&smtes;"}],[0,{v:"&late;",n:65024,o:"&lates;"}],[0,"&bumpE;"],[0,{v:"&PrecedesEqual;",n:824,o:"&NotPrecedesEqual;"}],[0,{v:"&sce;",n:824,o:"&NotSucceedsEqual;"}],[2,"&prE;"],[0,"&scE;"],[0,"&precneqq;"],[0,"&scnE;"],[0,"&prap;"],[0,"&scap;"],[0,"&precnapprox;"],[0,"&scnap;"],[0,"&Pr;"],[0,"&Sc;"],[0,"&subdot;"],[0,"&supdot;"],[0,"&subplus;"],[0,"&supplus;"],[0,"&submult;"],[0,"&supmult;"],[0,"&subedot;"],[0,"&supedot;"],[0,{v:"&subE;",n:824,o:"&nsubE;"}],[0,{v:"&supE;",n:824,o:"&nsupE;"}],[0,"&subsim;"],[0,"&supsim;"],[2,{v:"&subnE;",n:65024,o:"&varsubsetneqq;"}],[0,{v:"&supnE;",n:65024,o:"&varsupsetneqq;"}],[2,"&csub;"],[0,"&csup;"],[0,"&csube;"],[0,"&csupe;"],[0,"&subsup;"],[0,"&supsub;"],[0,"&subsub;"],[0,"&supsup;"],[0,"&suphsub;"],[0,"&supdsub;"],[0,"&forkv;"],[0,"&topfork;"],[0,"&mlcp;"],[8,"&Dashv;"],[1,"&Vdashl;"],[0,"&Barv;"],[0,"&vBar;"],[0,"&vBarv;"],[1,"&Vbar;"],[0,"&Not;"],[0,"&bNot;"],[0,"&rnmid;"],[0,"&cirmid;"],[0,"&midcir;"],[0,"&topcir;"],[0,"&nhpar;"],[0,"&parsim;"],[9,{v:"&parsl;",n:8421,o:"&nparsl;"}],[44343,{n:new Map(Le$2([[56476,"&Ascr;"],[1,"&Cscr;"],[0,"&Dscr;"],[2,"&Gscr;"],[2,"&Jscr;"],[0,"&Kscr;"],[2,"&Nscr;"],[0,"&Oscr;"],[0,"&Pscr;"],[0,"&Qscr;"],[1,"&Sscr;"],[0,"&Tscr;"],[0,"&Uscr;"],[0,"&Vscr;"],[0,"&Wscr;"],[0,"&Xscr;"],[0,"&Yscr;"],[0,"&Zscr;"],[0,"&ascr;"],[0,"&bscr;"],[0,"&cscr;"],[0,"&dscr;"],[1,"&fscr;"],[1,"&hscr;"],[0,"&iscr;"],[0,"&jscr;"],[0,"&kscr;"],[0,"&lscr;"],[0,"&mscr;"],[0,"&nscr;"],[1,"&pscr;"],[0,"&qscr;"],[0,"&rscr;"],[0,"&sscr;"],[0,"&tscr;"],[0,"&uscr;"],[0,"&vscr;"],[0,"&wscr;"],[0,"&xscr;"],[0,"&yscr;"],[0,"&zscr;"],[52,"&Afr;"],[0,"&Bfr;"],[1,"&Dfr;"],[0,"&Efr;"],[0,"&Ffr;"],[0,"&Gfr;"],[2,"&Jfr;"],[0,"&Kfr;"],[0,"&Lfr;"],[0,"&Mfr;"],[0,"&Nfr;"],[0,"&Ofr;"],[0,"&Pfr;"],[0,"&Qfr;"],[1,"&Sfr;"],[0,"&Tfr;"],[0,"&Ufr;"],[0,"&Vfr;"],[0,"&Wfr;"],[0,"&Xfr;"],[0,"&Yfr;"],[1,"&afr;"],[0,"&bfr;"],[0,"&cfr;"],[0,"&dfr;"],[0,"&efr;"],[0,"&ffr;"],[0,"&gfr;"],[0,"&hfr;"],[0,"&ifr;"],[0,"&jfr;"],[0,"&kfr;"],[0,"&lfr;"],[0,"&mfr;"],[0,"&nfr;"],[0,"&ofr;"],[0,"&pfr;"],[0,"&qfr;"],[0,"&rfr;"],[0,"&sfr;"],[0,"&tfr;"],[0,"&ufr;"],[0,"&vfr;"],[0,"&wfr;"],[0,"&xfr;"],[0,"&yfr;"],[0,"&zfr;"],[0,"&Aopf;"],[0,"&Bopf;"],[1,"&Dopf;"],[0,"&Eopf;"],[0,"&Fopf;"],[0,"&Gopf;"],[1,"&Iopf;"],[0,"&Jopf;"],[0,"&Kopf;"],[0,"&Lopf;"],[0,"&Mopf;"],[1,"&Oopf;"],[3,"&Sopf;"],[0,"&Topf;"],[0,"&Uopf;"],[0,"&Vopf;"],[0,"&Wopf;"],[0,"&Xopf;"],[0,"&Yopf;"],[1,"&aopf;"],[0,"&bopf;"],[0,"&copf;"],[0,"&dopf;"],[0,"&eopf;"],[0,"&fopf;"],[0,"&gopf;"],[0,"&hopf;"],[0,"&iopf;"],[0,"&jopf;"],[0,"&kopf;"],[0,"&lopf;"],[0,"&mopf;"],[0,"&nopf;"],[0,"&oopf;"],[0,"&popf;"],[0,"&qopf;"],[0,"&ropf;"],[0,"&sopf;"],[0,"&topf;"],[0,"&uopf;"],[0,"&vopf;"],[0,"&wopf;"],[0,"&xopf;"],[0,"&yopf;"],[0,"&zopf;"]]))}],[8906,"&fflig;"],[0,"&filig;"],[0,"&fllig;"],[0,"&ffilig;"],[0,"&ffllig;"]]));var je={};(function(t){Object.defineProperty(t,"__esModule",{value:!0}),t.escapeText=t.escapeAttribute=t.escapeUTF8=t.escape=t.encodeXML=t.getCodePoint=t.xmlReplacer=void 0,t.xmlReplacer=/["&'<>$\x80-\uFFFF]/g;var e=new Map([[34,"&quot;"],[38,"&amp;"],[39,"&apos;"],[60,"&lt;"],[62,"&gt;"]]);t.getCodePoint=String.prototype.codePointAt!=null?function(n,a){return n.codePointAt(a)}:function(n,a){return (n.charCodeAt(a)&64512)===55296?(n.charCodeAt(a)-55296)*1024+n.charCodeAt(a+1)-56320+65536:n.charCodeAt(a)};function u(n){for(var a="",i=0,l;(l=t.xmlReplacer.exec(n))!==null;){var o=l.index,d=n.charCodeAt(o),f=e.get(d);f!==void 0?(a+=n.substring(i,o)+f,i=o+1):(a+="".concat(n.substring(i,o),"&#x").concat((0, t.getCodePoint)(n,o).toString(16),";"),i=t.xmlReplacer.lastIndex+=+((d&64512)===55296));}return a+n.substr(i)}t.encodeXML=u,t.escape=u;function r(n,a){return function(l){for(var o,d=0,f="";o=n.exec(l);)d!==o.index&&(f+=l.substring(d,o.index)),f+=a.get(o[0].charCodeAt(0)),d=o.index+1;return f+l.substring(d)}}t.escapeUTF8=r(/[&<>'"]/g,e),t.escapeAttribute=r(/["&\u00A0]/g,new Map([[34,"&quot;"],[38,"&amp;"],[160,"&nbsp;"]])),t.escapeText=r(/[&<>\u00A0]/g,new Map([[38,"&amp;"],[60,"&lt;"],[62,"&gt;"],[160,"&nbsp;"]]));})(je);var er=qs&&qs.__importDefault||function(t){return t&&t.__esModule?t:{default:t}};Object.defineProperty(he$1,"__esModule",{value:!0});he$1.encodeNonAsciiHTML=he$1.encodeHTML=void 0;var ur=er(xu),Ft=je,tr=/[\t\n!-,./:-@[-`\f{-}$\x80-\uFFFF]/g;function rr(t){return Ct$2(tr,t)}he$1.encodeHTML=rr;function nr(t){return Ct$2(Ft.xmlReplacer,t)}he$1.encodeNonAsciiHTML=nr;function Ct$2(t,e){for(var u="",r=0,n;(n=t.exec(e))!==null;){var a=n.index;u+=e.substring(r,a);var i=e.charCodeAt(a),l=ur.default.get(i);if(typeof l=="object"){if(a+1<e.length){var o=e.charCodeAt(a+1),d=typeof l.n=="number"?l.n===o?l.o:void 0:l.n.get(o);if(d!==void 0){u+=d,r=t.lastIndex+=1;continue}}l=l.v;}if(l!==void 0)u+=l,r=a+1;else {var f=(0, Ft.getCodePoint)(e,a);u+="&#x".concat(f.toString(16),";"),r=t.lastIndex+=+(f!==i);}}return u+e.substr(r)}(function(t){Object.defineProperty(t,"__esModule",{value:!0}),t.decodeXMLStrict=t.decodeHTML5Strict=t.decodeHTML4Strict=t.decodeHTML5=t.decodeHTML4=t.decodeHTMLAttribute=t.decodeHTMLStrict=t.decodeHTML=t.decodeXML=t.DecodingMode=t.EntityDecoder=t.encodeHTML5=t.encodeHTML4=t.encodeNonAsciiHTML=t.encodeHTML=t.escapeText=t.escapeAttribute=t.escapeUTF8=t.escape=t.encodeXML=t.encode=t.decodeStrict=t.decode=t.EncodingMode=t.EntityLevel=void 0;var e=we$1,u=he$1,r=je,n;(function(s){s[s.XML=0]="XML",s[s.HTML=1]="HTML";})(n=t.EntityLevel||(t.EntityLevel={}));var a;(function(s){s[s.UTF8=0]="UTF8",s[s.ASCII=1]="ASCII",s[s.Extensive=2]="Extensive",s[s.Attribute=3]="Attribute",s[s.Text=4]="Text";})(a=t.EncodingMode||(t.EncodingMode={}));function i(s,c){c===void 0&&(c=n.XML);var x=typeof c=="number"?c:c.level;if(x===n.HTML){var y=typeof c=="object"?c.mode:void 0;return (0, e.decodeHTML)(s,y)}return (0, e.decodeXML)(s)}t.decode=i;function l(s,c){var x;c===void 0&&(c=n.XML);var y=typeof c=="number"?{level:c}:c;return (x=y.mode)!==null&&x!==void 0||(y.mode=e.DecodingMode.Strict),i(s,y)}t.decodeStrict=l;function o(s,c){c===void 0&&(c=n.XML);var x=typeof c=="number"?{level:c}:c;return x.mode===a.UTF8?(0, r.escapeUTF8)(s):x.mode===a.Attribute?(0, r.escapeAttribute)(s):x.mode===a.Text?(0, r.escapeText)(s):x.level===n.HTML?x.mode===a.ASCII?(0, u.encodeNonAsciiHTML)(s):(0, u.encodeHTML)(s):(0, r.encodeXML)(s)}t.encode=o;var d=je;Object.defineProperty(t,"encodeXML",{enumerable:!0,get:function(){return d.encodeXML}}),Object.defineProperty(t,"escape",{enumerable:!0,get:function(){return d.escape}}),Object.defineProperty(t,"escapeUTF8",{enumerable:!0,get:function(){return d.escapeUTF8}}),Object.defineProperty(t,"escapeAttribute",{enumerable:!0,get:function(){return d.escapeAttribute}}),Object.defineProperty(t,"escapeText",{enumerable:!0,get:function(){return d.escapeText}});var f=he$1;Object.defineProperty(t,"encodeHTML",{enumerable:!0,get:function(){return f.encodeHTML}}),Object.defineProperty(t,"encodeNonAsciiHTML",{enumerable:!0,get:function(){return f.encodeNonAsciiHTML}}),Object.defineProperty(t,"encodeHTML4",{enumerable:!0,get:function(){return f.encodeHTML}}),Object.defineProperty(t,"encodeHTML5",{enumerable:!0,get:function(){return f.encodeHTML}});var p=we$1;Object.defineProperty(t,"EntityDecoder",{enumerable:!0,get:function(){return p.EntityDecoder}}),Object.defineProperty(t,"DecodingMode",{enumerable:!0,get:function(){return p.DecodingMode}}),Object.defineProperty(t,"decodeXML",{enumerable:!0,get:function(){return p.decodeXML}}),Object.defineProperty(t,"decodeHTML",{enumerable:!0,get:function(){return p.decodeHTML}}),Object.defineProperty(t,"decodeHTMLStrict",{enumerable:!0,get:function(){return p.decodeHTMLStrict}}),Object.defineProperty(t,"decodeHTMLAttribute",{enumerable:!0,get:function(){return p.decodeHTMLAttribute}}),Object.defineProperty(t,"decodeHTML4",{enumerable:!0,get:function(){return p.decodeHTML}}),Object.defineProperty(t,"decodeHTML5",{enumerable:!0,get:function(){return p.decodeHTML}}),Object.defineProperty(t,"decodeHTML4Strict",{enumerable:!0,get:function(){return p.decodeHTMLStrict}}),Object.defineProperty(t,"decodeHTML5Strict",{enumerable:!0,get:function(){return p.decodeHTMLStrict}}),Object.defineProperty(t,"decodeXMLStrict",{enumerable:!0,get:function(){return p.decodeXML}});})(wt);var me$1={};Object.defineProperty(me$1,"__esModule",{value:!0});me$1.attributeNames=me$1.elementNames=void 0;me$1.elementNames=new Map(["altGlyph","altGlyphDef","altGlyphItem","animateColor","animateMotion","animateTransform","clipPath","feBlend","feColorMatrix","feComponentTransfer","feComposite","feConvolveMatrix","feDiffuseLighting","feDisplacementMap","feDistantLight","feDropShadow","feFlood","feFuncA","feFuncB","feFuncG","feFuncR","feGaussianBlur","feImage","feMerge","feMergeNode","feMorphology","feOffset","fePointLight","feSpecularLighting","feSpotLight","feTile","feTurbulence","foreignObject","glyphRef","linearGradient","radialGradient","textPath"].map(function(t){return [t.toLowerCase(),t]}));me$1.attributeNames=new Map(["definitionURL","attributeName","attributeType","baseFrequency","baseProfile","calcMode","clipPathUnits","diffuseConstant","edgeMode","filterUnits","glyphRef","gradientTransform","gradientUnits","kernelMatrix","kernelUnitLength","keyPoints","keySplines","keyTimes","lengthAdjust","limitingConeAngle","markerHeight","markerUnits","markerWidth","maskContentUnits","maskUnits","numOctaves","pathLength","patternContentUnits","patternTransform","patternUnits","pointsAtX","pointsAtY","pointsAtZ","preserveAlpha","preserveAspectRatio","primitiveUnits","refX","refY","repeatCount","repeatDur","requiredExtensions","requiredFeatures","specularConstant","specularExponent","spreadMethod","startOffset","stdDeviation","stitchTiles","surfaceScale","systemLanguage","tableValues","targetX","targetY","textLength","viewBox","viewTarget","xChannelSelector","yChannelSelector","zoomAndPan"].map(function(t){return [t.toLowerCase(),t]}));var ge=qs&&qs.__assign||function(){return ge=Object.assign||function(t){for(var e,u=1,r=arguments.length;u<r;u++){e=arguments[u];for(var n in e)Object.prototype.hasOwnProperty.call(e,n)&&(t[n]=e[n]);}return t},ge.apply(this,arguments)},ar=qs&&qs.__createBinding||(Object.create?function(t,e,u,r){r===void 0&&(r=u);var n=Object.getOwnPropertyDescriptor(e,u);(!n||("get"in n?!e.__esModule:n.writable||n.configurable))&&(n={enumerable:!0,get:function(){return e[u]}}),Object.defineProperty(t,r,n);}:function(t,e,u,r){r===void 0&&(r=u),t[r]=e[u];}),ir=qs&&qs.__setModuleDefault||(Object.create?function(t,e){Object.defineProperty(t,"default",{enumerable:!0,value:e});}:function(t,e){t.default=e;}),sr=qs&&qs.__importStar||function(t){if(t&&t.__esModule)return t;var e={};if(t!=null)for(var u in t)u!=="default"&&Object.prototype.hasOwnProperty.call(t,u)&&ar(e,t,u);return ir(e,t),e};Object.defineProperty(Te,"__esModule",{value:!0});Te.render=void 0;var ae$1=sr(De),ze$1=wt,kt$1=me$1,cr=new Set(["style","script","xmp","iframe","noembed","noframes","plaintext","noscript"]);function or(t){return t.replace(/"/g,"&quot;")}function lr(t,e){var u;if(t){var r=((u=e.encodeEntities)!==null&&u!==void 0?u:e.decodeEntities)===!1?or:e.xmlMode||e.encodeEntities!=="utf8"?ze$1.encodeXML:ze$1.escapeAttribute;return Object.keys(t).map(function(n){var a,i,l=(a=t[n])!==null&&a!==void 0?a:"";return e.xmlMode==="foreign"&&(n=(i=kt$1.attributeNames.get(n))!==null&&i!==void 0?i:n),!e.emptyAttrs&&!e.xmlMode&&l===""?n:"".concat(n,'="').concat(r(l),'"')}).join(" ")}}var Hu=new Set(["area","base","basefont","br","col","command","embed","frame","hr","img","input","isindex","keygen","link","meta","param","source","track","wbr"]);function Xe(t,e){e===void 0&&(e={});for(var u=("length"in t)?t:[t],r="",n=0;n<u.length;n++)r+=dr(u[n],e);return r}Te.render=Xe;Te.default=Xe;function dr(t,e){switch(t.type){case ae$1.Root:return Xe(t.children,e);case ae$1.Doctype:case ae$1.Directive:return pr(t);case ae$1.Comment:return Dr(t);case ae$1.CDATA:return mr(t);case ae$1.Script:case ae$1.Style:case ae$1.Tag:return br(t,e);case ae$1.Text:return gr(t,e)}}var fr=new Set(["mi","mo","mn","ms","mtext","annotation-xml","foreignObject","desc","title"]),hr=new Set(["svg","math"]);function br(t,e){var u;e.xmlMode==="foreign"&&(t.name=(u=kt$1.elementNames.get(t.name))!==null&&u!==void 0?u:t.name,t.parent&&fr.has(t.parent.name)&&(e=ge(ge({},e),{xmlMode:!1}))),!e.xmlMode&&hr.has(t.name)&&(e=ge(ge({},e),{xmlMode:"foreign"}));var r="<".concat(t.name),n=lr(t.attribs,e);return n&&(r+=" ".concat(n)),t.children.length===0&&(e.xmlMode?e.selfClosingTags!==!1:e.selfClosingTags&&Hu.has(t.name))?(e.xmlMode||(r+=" "),r+="/>"):(r+=">",t.children.length>0&&(r+=Xe(t.children,e)),(e.xmlMode||!Hu.has(t.name))&&(r+="</".concat(t.name,">"))),r}function pr(t){return "<".concat(t.data,">")}function gr(t,e){var u,r=t.data||"";return ((u=e.encodeEntities)!==null&&u!==void 0?u:e.decodeEntities)!==!1&&!(!e.xmlMode&&t.parent&&cr.has(t.parent.name))&&(r=e.xmlMode||e.encodeEntities!=="utf8"?(0, ze$1.encodeXML)(r):(0, ze$1.escapeText)(r)),r}function mr(t){return "<![CDATA[".concat(t.children[0].data,"]]>")}function Dr(t){return "<!--".concat(t.data,"-->")}var xr=qs&&qs.__importDefault||function(t){return t&&t.__esModule?t:{default:t}};Object.defineProperty(K,"__esModule",{value:!0});K.innerText=K.textContent=K.getText=K.getInnerHTML=K.getOuterHTML=void 0;var re$1=se$1,Ar=xr(Te),yr=De;function Tt$1(t,e){return (0, Ar.default)(t,e)}K.getOuterHTML=Tt$1;function vr(t,e){return (0, re$1.hasChildren)(t)?t.children.map(function(u){return Tt$1(u,e)}).join(""):""}K.getInnerHTML=vr;function Re(t){return Array.isArray(t)?t.map(Re).join(""):(0, re$1.isTag)(t)?t.name==="br"?`
`:Re(t.children):(0, re$1.isCDATA)(t)?Re(t.children):(0, re$1.isText)(t)?t.data:""}K.getText=Re;function nu(t){return Array.isArray(t)?t.map(nu).join(""):(0, re$1.hasChildren)(t)&&!(0, re$1.isComment)(t)?nu(t.children):(0, re$1.isText)(t)?t.data:""}K.textContent=nu;function au(t){return Array.isArray(t)?t.map(au).join(""):(0, re$1.hasChildren)(t)&&(t.type===yr.ElementType.Tag||(0, re$1.isCDATA)(t))?au(t.children):(0, re$1.isText)(t)?t.data:""}K.innerText=au;var z={};Object.defineProperty(z,"__esModule",{value:!0});z.prevElementSibling=z.nextElementSibling=z.getName=z.hasAttrib=z.getAttributeValue=z.getSiblings=z.getParent=z.getChildren=void 0;var Au=se$1;function St$1(t){return (0, Au.hasChildren)(t)?t.children:[]}z.getChildren=St$1;function _t$1(t){return t.parent||null}z.getParent=_t$1;function Er(t){var e,u,r=_t$1(t);if(r!=null)return St$1(r);for(var n=[t],a=t.prev,i=t.next;a!=null;)n.unshift(a),e=a,a=e.prev;for(;i!=null;)n.push(i),u=i,i=u.next;return n}z.getSiblings=Er;function wr(t,e){var u;return (u=t.attribs)===null||u===void 0?void 0:u[e]}z.getAttributeValue=wr;function Fr(t,e){return t.attribs!=null&&Object.prototype.hasOwnProperty.call(t.attribs,e)&&t.attribs[e]!=null}z.hasAttrib=Fr;function Cr(t){return t.name}z.getName=Cr;function kr(t){for(var e,u=t.next;u!==null&&!(0, Au.isTag)(u);)e=u,u=e.next;return u}z.nextElementSibling=kr;function Tr(t){for(var e,u=t.prev;u!==null&&!(0, Au.isTag)(u);)e=u,u=e.prev;return u}z.prevElementSibling=Tr;var Z={};Object.defineProperty(Z,"__esModule",{value:!0});Z.prepend=Z.prependChild=Z.append=Z.appendChild=Z.replaceElement=Z.removeElement=void 0;function Se(t){if(t.prev&&(t.prev.next=t.next),t.next&&(t.next.prev=t.prev),t.parent){var e=t.parent.children,u=e.lastIndexOf(t);u>=0&&e.splice(u,1);}t.next=null,t.prev=null,t.parent=null;}Z.removeElement=Se;function Sr(t,e){var u=e.prev=t.prev;u&&(u.next=e);var r=e.next=t.next;r&&(r.prev=e);var n=e.parent=t.parent;if(n){var a=n.children;a[a.lastIndexOf(t)]=e,t.parent=null;}}Z.replaceElement=Sr;function _r(t,e){if(Se(e),e.next=null,e.parent=t,t.children.push(e)>1){var u=t.children[t.children.length-2];u.next=e,e.prev=u;}else e.prev=null;}Z.appendChild=_r;function Br(t,e){Se(e);var u=t.parent,r=t.next;if(e.next=r,e.prev=t,t.next=e,e.parent=u,r){if(r.prev=e,u){var n=u.children;n.splice(n.lastIndexOf(r),0,e);}}else u&&u.children.push(e);}Z.append=Br;function Ir(t,e){if(Se(e),e.parent=t,e.prev=null,t.children.unshift(e)!==1){var u=t.children[1];u.prev=e,e.next=u;}else e.next=null;}Z.prependChild=Ir;function Nr(t,e){Se(e);var u=t.parent;if(u){var r=u.children;r.splice(r.indexOf(t),0,e);}t.prev&&(t.prev.next=e),e.parent=u,e.prev=t.prev,e.next=t,t.prev=e;}Z.prepend=Nr;var $={};Object.defineProperty($,"__esModule",{value:!0});$.findAll=$.existsOne=$.findOne=$.findOneChild=$.find=$.filter=void 0;var Qe=se$1;function Lr(t,e,u,r){return u===void 0&&(u=!0),r===void 0&&(r=1/0),Bt(t,Array.isArray(e)?e:[e],u,r)}$.filter=Lr;function Bt(t,e,u,r){for(var n=[],a=[e],i=[0];;){if(i[0]>=a[0].length){if(i.length===1)return n;a.shift(),i.shift();continue}var l=a[0][i[0]++];if(t(l)&&(n.push(l),--r<=0))return n;u&&(0, Qe.hasChildren)(l)&&l.children.length>0&&(i.unshift(0),a.unshift(l.children));}}$.find=Bt;function Or(t,e){return e.find(t)}$.findOneChild=Or;function It(t,e,u){u===void 0&&(u=!0);for(var r=null,n=0;n<e.length&&!r;n++){var a=e[n];if((0, Qe.isTag)(a))t(a)?r=a:u&&a.children.length>0&&(r=It(t,a.children,!0));else continue}return r}$.findOne=It;function Nt$1(t,e){return e.some(function(u){return (0, Qe.isTag)(u)&&(t(u)||Nt$1(t,u.children))})}$.existsOne=Nt$1;function qr(t,e){for(var u=[],r=[e],n=[0];;){if(n[0]>=r[0].length){if(r.length===1)return u;r.shift(),n.shift();continue}var a=r[0][n[0]++];(0, Qe.isTag)(a)&&(t(a)&&u.push(a),a.children.length>0&&(n.unshift(0),r.unshift(a.children)));}}$.findAll=qr;var Y$1={};Object.defineProperty(Y$1,"__esModule",{value:!0});Y$1.getElementsByTagType=Y$1.getElementsByTagName=Y$1.getElementById=Y$1.getElements=Y$1.testElement=void 0;var de$1=se$1,We$1=$,Ue={tag_name:function(t){return typeof t=="function"?function(e){return (0, de$1.isTag)(e)&&t(e.name)}:t==="*"?de$1.isTag:function(e){return (0, de$1.isTag)(e)&&e.name===t}},tag_type:function(t){return typeof t=="function"?function(e){return t(e.type)}:function(e){return e.type===t}},tag_contains:function(t){return typeof t=="function"?function(e){return (0, de$1.isText)(e)&&t(e.data)}:function(e){return (0, de$1.isText)(e)&&e.data===t}}};function Lt$1(t,e){return typeof e=="function"?function(u){return (0, de$1.isTag)(u)&&e(u.attribs[t])}:function(u){return (0, de$1.isTag)(u)&&u.attribs[t]===e}}function Rr(t,e){return function(u){return t(u)||e(u)}}function Ot(t){var e=Object.keys(t).map(function(u){var r=t[u];return Object.prototype.hasOwnProperty.call(Ue,u)?Ue[u](r):Lt$1(u,r)});return e.length===0?null:e.reduce(Rr)}function Pr(t,e){var u=Ot(t);return u?u(e):!0}Y$1.testElement=Pr;function Mr(t,e,u,r){r===void 0&&(r=1/0);var n=Ot(t);return n?(0, We$1.filter)(n,e,u,r):[]}Y$1.getElements=Mr;function Hr(t,e,u){return u===void 0&&(u=!0),Array.isArray(e)||(e=[e]),(0, We$1.findOne)(Lt$1("id",t),e,u)}Y$1.getElementById=Hr;function jr(t,e,u,r){return u===void 0&&(u=!0),r===void 0&&(r=1/0),(0, We$1.filter)(Ue.tag_name(t),e,u,r)}Y$1.getElementsByTagName=jr;function zr(t,e,u,r){return u===void 0&&(u=!0),r===void 0&&(r=1/0),(0, We$1.filter)(Ue.tag_type(t),e,u,r)}Y$1.getElementsByTagType=zr;var qt$1={};(function(t){Object.defineProperty(t,"__esModule",{value:!0}),t.uniqueSort=t.compareDocumentPosition=t.DocumentPosition=t.removeSubsets=void 0;var e=se$1;function u(i){for(var l=i.length;--l>=0;){var o=i[l];if(l>0&&i.lastIndexOf(o,l-1)>=0){i.splice(l,1);continue}for(var d=o.parent;d;d=d.parent)if(i.includes(d)){i.splice(l,1);break}}return i}t.removeSubsets=u;var r;(function(i){i[i.DISCONNECTED=1]="DISCONNECTED",i[i.PRECEDING=2]="PRECEDING",i[i.FOLLOWING=4]="FOLLOWING",i[i.CONTAINS=8]="CONTAINS",i[i.CONTAINED_BY=16]="CONTAINED_BY";})(r=t.DocumentPosition||(t.DocumentPosition={}));function n(i,l){var o=[],d=[];if(i===l)return 0;for(var f=(0, e.hasChildren)(i)?i:i.parent;f;)o.unshift(f),f=f.parent;for(f=(0, e.hasChildren)(l)?l:l.parent;f;)d.unshift(f),f=f.parent;for(var p=Math.min(o.length,d.length),s=0;s<p&&o[s]===d[s];)s++;if(s===0)return r.DISCONNECTED;var c=o[s-1],x=c.children,y=o[s],v=d[s];return x.indexOf(y)>x.indexOf(v)?c===l?r.FOLLOWING|r.CONTAINED_BY:r.FOLLOWING:c===i?r.PRECEDING|r.CONTAINS:r.PRECEDING}t.compareDocumentPosition=n;function a(i){return i=i.filter(function(l,o,d){return !d.includes(l,o+1)}),i.sort(function(l,o){var d=n(l,o);return d&r.PRECEDING?-1:d&r.FOLLOWING?1:0}),i}t.uniqueSort=a;})(qt$1);var Ke$1={};Object.defineProperty(Ke$1,"__esModule",{value:!0});Ke$1.getFeed=void 0;var Ur=K,_e=Y$1;function $r(t){var e=$e(Qr,t);return e?e.name==="feed"?Vr(e):Gr(e):null}Ke$1.getFeed=$r;function Vr(t){var e,u=t.children,r={type:"atom",items:(0, _e.getElementsByTagName)("entry",u).map(function(i){var l,o=i.children,d={media:Rt$1(o)};G(d,"id","id",o),G(d,"title","title",o);var f=(l=$e("link",o))===null||l===void 0?void 0:l.attribs.href;f&&(d.link=f);var p=ce$1("summary",o)||ce$1("content",o);p&&(d.description=p);var s=ce$1("updated",o);return s&&(d.pubDate=new Date(s)),d})};G(r,"id","id",u),G(r,"title","title",u);var n=(e=$e("link",u))===null||e===void 0?void 0:e.attribs.href;n&&(r.link=n),G(r,"description","subtitle",u);var a=ce$1("updated",u);return a&&(r.updated=new Date(a)),G(r,"author","email",u,!0),r}function Gr(t){var e,u,r=(u=(e=$e("channel",t.children))===null||e===void 0?void 0:e.children)!==null&&u!==void 0?u:[],n={type:t.name.substr(0,3),id:"",items:(0, _e.getElementsByTagName)("item",t.children).map(function(i){var l=i.children,o={media:Rt$1(l)};G(o,"id","guid",l),G(o,"title","title",l),G(o,"link","link",l),G(o,"description","description",l);var d=ce$1("pubDate",l)||ce$1("dc:date",l);return d&&(o.pubDate=new Date(d)),o})};G(n,"title","title",r),G(n,"link","link",r),G(n,"description","description",r);var a=ce$1("lastBuildDate",r);return a&&(n.updated=new Date(a)),G(n,"author","managingEditor",r,!0),n}var Zr=["url","type","lang"],Xr=["fileSize","bitrate","framerate","samplingrate","channels","duration","height","width"];function Rt$1(t){return (0, _e.getElementsByTagName)("media:content",t).map(function(e){for(var u=e.attribs,r={medium:u.medium,isDefault:!!u.isDefault},n=0,a=Zr;n<a.length;n++){var i=a[n];u[i]&&(r[i]=u[i]);}for(var l=0,o=Xr;l<o.length;l++){var i=o[l];u[i]&&(r[i]=parseInt(u[i],10));}return u.expression&&(r.expression=u.expression),r})}function $e(t,e){return (0, _e.getElementsByTagName)(t,e,!0,1)[0]}function ce$1(t,e,u){return u===void 0&&(u=!1),(0, Ur.textContent)((0, _e.getElementsByTagName)(t,e,u,1)).trim()}function G(t,e,u,r,n){n===void 0&&(n=!1);var a=ce$1(u,r,n);a&&(t[e]=a);}function Qr(t){return t==="rss"||t==="feed"||t==="rdf:RDF"}(function(t){var e=qs&&qs.__createBinding||(Object.create?function(n,a,i,l){l===void 0&&(l=i);var o=Object.getOwnPropertyDescriptor(a,i);(!o||("get"in o?!a.__esModule:o.writable||o.configurable))&&(o={enumerable:!0,get:function(){return a[i]}}),Object.defineProperty(n,l,o);}:function(n,a,i,l){l===void 0&&(l=i),n[l]=a[i];}),u=qs&&qs.__exportStar||function(n,a){for(var i in n)i!=="default"&&!Object.prototype.hasOwnProperty.call(a,i)&&e(a,n,i);};Object.defineProperty(t,"__esModule",{value:!0}),t.hasChildren=t.isDocument=t.isComment=t.isText=t.isCDATA=t.isTag=void 0,u(K,t),u(z,t),u(Z,t),u($,t),u(Y$1,t),u(qt$1,t),u(Ke$1,t);var r=se$1;Object.defineProperty(t,"isTag",{enumerable:!0,get:function(){return r.isTag}}),Object.defineProperty(t,"isCDATA",{enumerable:!0,get:function(){return r.isCDATA}}),Object.defineProperty(t,"isText",{enumerable:!0,get:function(){return r.isText}}),Object.defineProperty(t,"isComment",{enumerable:!0,get:function(){return r.isComment}}),Object.defineProperty(t,"isDocument",{enumerable:!0,get:function(){return r.isDocument}}),Object.defineProperty(t,"hasChildren",{enumerable:!0,get:function(){return r.hasChildren}});})(qe$1);(function(t){var e=qs&&qs.__createBinding||(Object.create?function(E,C,F,S){S===void 0&&(S=F);var _=Object.getOwnPropertyDescriptor(C,F);(!_||("get"in _?!C.__esModule:_.writable||_.configurable))&&(_={enumerable:!0,get:function(){return C[F]}}),Object.defineProperty(E,S,_);}:function(E,C,F,S){S===void 0&&(S=F),E[S]=C[F];}),u=qs&&qs.__setModuleDefault||(Object.create?function(E,C){Object.defineProperty(E,"default",{enumerable:!0,value:C});}:function(E,C){E.default=C;}),r=qs&&qs.__importStar||function(E){if(E&&E.__esModule)return E;var C={};if(E!=null)for(var F in E)F!=="default"&&Object.prototype.hasOwnProperty.call(E,F)&&e(C,E,F);return u(C,E),C},n=qs&&qs.__importDefault||function(E){return E&&E.__esModule?E:{default:E}};Object.defineProperty(t,"__esModule",{value:!0}),t.DomUtils=t.parseFeed=t.getFeed=t.ElementType=t.Tokenizer=t.createDomStream=t.parseDOM=t.parseDocument=t.DefaultHandler=t.DomHandler=t.Parser=void 0;var a=Ee,i=Ee;Object.defineProperty(t,"Parser",{enumerable:!0,get:function(){return i.Parser}});var l=se$1,o=se$1;Object.defineProperty(t,"DomHandler",{enumerable:!0,get:function(){return o.DomHandler}}),Object.defineProperty(t,"DefaultHandler",{enumerable:!0,get:function(){return o.DomHandler}});function d(E,C){var F=new l.DomHandler(void 0,C);return new a.Parser(F,C).end(E),F.root}t.parseDocument=d;function f(E,C){return d(E,C).children}t.parseDOM=f;function p(E,C,F){var S=new l.DomHandler(E,C,F);return new a.Parser(S,C)}t.createDomStream=p;var s=bu;Object.defineProperty(t,"Tokenizer",{enumerable:!0,get:function(){return n(s).default}}),t.ElementType=r(De);var c=qe$1,x=qe$1;Object.defineProperty(t,"getFeed",{enumerable:!0,get:function(){return x.getFeed}});var y={xmlMode:!0};function v(E,C){return C===void 0&&(C=y),(0, c.getFeed)(f(E,C))}t.parseFeed=v,t.DomUtils=r(qe$1);})(dt$2);var Wr=t=>{if(typeof t!="string")throw new TypeError("Expected a string");return t.replace(/[|\\{}()[\]^$+*?.]/g,"\\$&").replace(/-/g,"\\x2d")},yu={};Object.defineProperty(yu,"__esModule",{value:!0});/*!
 * is-plain-object <https://github.com/jonschlinkert/is-plain-object>
 *
 * Copyright (c) 2014-2017, Jon Schlinkert.
 * Released under the MIT License.
 */function ju(t){return Object.prototype.toString.call(t)==="[object Object]"}function Kr(t){var e,u;return ju(t)===!1?!1:(e=t.constructor,e===void 0?!0:(u=e.prototype,!(ju(u)===!1||u.hasOwnProperty("isPrototypeOf")===!1)))}yu.isPlainObject=Kr;var Pt$1={exports:{}};(function(t){(function(e,u){t.exports?t.exports=u():e.parseSrcset=u();})(qs,function(){return function(e){function u(S){return S===" "||S==="	"||S===`
`||S==="\f"||S==="\r"}function r(S){var _,M=S.exec(e.substring(v));if(M)return _=M[0],v+=_.length,_}for(var n=e.length,a=/^[ \t\n\r\u000c]+/,i=/^[, \t\n\r\u000c]+/,l=/^[^ \t\n\r\u000c]+/,o=/[,]+$/,d=/^\d+$/,f=/^-?(?:[0-9]+|[0-9]*\.[0-9]+)(?:[eE][+-]?[0-9]+)?$/,p,s,c,x,y,v=0,E=[];;){if(r(i),v>=n)return E;p=r(l),s=[],p.slice(-1)===","?(p=p.replace(o,""),F()):C();}function C(){for(r(a),c="",x="in descriptor";;){if(y=e.charAt(v),x==="in descriptor")if(u(y))c&&(s.push(c),c="",x="after descriptor");else if(y===","){v+=1,c&&s.push(c),F();return}else if(y==="(")c=c+y,x="in parens";else if(y===""){c&&s.push(c),F();return}else c=c+y;else if(x==="in parens")if(y===")")c=c+y,x="in descriptor";else if(y===""){s.push(c),F();return}else c=c+y;else if(x==="after descriptor"&&!u(y))if(y===""){F();return}else x="in descriptor",v-=1;v+=1;}}function F(){var S=!1,_,M,U,V,J={},Q,b,D,A,k;for(V=0;V<s.length;V++)Q=s[V],b=Q[Q.length-1],D=Q.substring(0,Q.length-1),A=parseInt(D,10),k=parseFloat(D),d.test(D)&&b==="w"?((_||M)&&(S=!0),A===0?S=!0:_=A):f.test(D)&&b==="x"?((_||M||U)&&(S=!0),k<0?S=!0:M=k):d.test(D)&&b==="h"?((U||M)&&(S=!0),A===0?S=!0:U=A):S=!0;S?console&&console.log&&console.log("Invalid srcset descriptor found in '"+e+"' at '"+Q+"'."):(J.url=p,_&&(J.w=_),M&&(J.d=M),U&&(J.h=U),E.push(J));}}});})(Pt$1);var Yr=Pt$1.exports;const Jr=dt$2,zu=Wr,{isPlainObject:en$1}=yu,Uu=zr$1,un$1=Yr,{parse:tn$1}=postcss,rn$1=["img","audio","video","picture","svg","object","map","iframe","embed"],nn$1=["script","style"];function Ae$1(t,e){t&&Object.keys(t).forEach(function(u){e(t[u],u);});}function ie(t,e){return {}.hasOwnProperty.call(t,e)}function $u(t,e){const u=[];return Ae$1(t,function(r){e(r)&&u.push(r);}),u}function an$1(t){for(const e in t)if(ie(t,e))return !1;return !0}function sn$1(t){return t.map(function(e){if(!e.url)throw new Error("URL missing");return e.url+(e.w?` ${e.w}w`:"")+(e.h?` ${e.h}h`:"")+(e.d?` ${e.d}x`:"")}).join(", ")}var cn$1=Fe;const on$1=/^[^\0\t\n\f\r /<=>]+$/;function Fe(t,e,u){if(t==null)return "";typeof t=="number"&&(t=t.toString());let r="",n="";function a(h,m){const g=this;this.tag=h,this.attribs=m||{},this.tagPosition=r.length,this.text="",this.mediaChildren=[],this.updateParentNodeText=function(){if(v.length){const w=v[v.length-1];w.text+=g.text;}},this.updateParentNodeMediaChildren=function(){v.length&&rn$1.includes(this.tag)&&v[v.length-1].mediaChildren.push(this.tag);};}e=Object.assign({},Fe.defaults,e),e.parser=Object.assign({},ln$1,e.parser);const i=function(h){return e.allowedTags===!1||(e.allowedTags||[]).indexOf(h)>-1};nn$1.forEach(function(h){i(h)&&!e.allowVulnerableTags&&console.warn(`

⚠️ Your \`allowedTags\` option includes, \`${h}\`, which is inherently
vulnerable to XSS attacks. Please remove it from \`allowedTags\`.
Or, to disable this warning, add the \`allowVulnerableTags\` option
and ensure you are accounting for this risk.

`);});const l=e.nonTextTags||["script","style","textarea","option"];let o,d;e.allowedAttributes&&(o={},d={},Ae$1(e.allowedAttributes,function(h,m){o[m]=[];const g=[];h.forEach(function(w){typeof w=="string"&&w.indexOf("*")>=0?g.push(zu(w).replace(/\\\*/g,".*")):o[m].push(w);}),g.length&&(d[m]=new RegExp("^("+g.join("|")+")$"));}));const f={},p={},s={};Ae$1(e.allowedClasses,function(h,m){if(o&&(ie(o,m)||(o[m]=[]),o[m].push("class")),f[m]=h,Array.isArray(h)){const g=[];f[m]=[],s[m]=[],h.forEach(function(w){typeof w=="string"&&w.indexOf("*")>=0?g.push(zu(w).replace(/\\\*/g,".*")):w instanceof RegExp?s[m].push(w):f[m].push(w);}),g.length&&(p[m]=new RegExp("^("+g.join("|")+")$"));}});const c={};let x;Ae$1(e.transformTags,function(h,m){let g;typeof h=="function"?g=h:typeof h=="string"&&(g=Fe.simpleTransform(h)),m==="*"?x=g:c[m]=g;});let y,v,E,C,F,S,_=!1;U();const M=new Jr.Parser({onopentag:function(h,m){if(e.enforceHtmlBoundary&&h==="html"&&U(),F){S++;return}const g=new a(h,m);v.push(g);let w=!1;const j=!!g.text;let H;if(ie(c,h)&&(H=c[h](h,m),g.attribs=m=H.attribs,H.text!==void 0&&(g.innerText=H.text),h!==H.tagName&&(g.name=h=H.tagName,C[y]=H.tagName)),x&&(H=x(h,m),g.attribs=m=H.attribs,h!==H.tagName&&(g.name=h=H.tagName,C[y]=H.tagName)),(!i(h)||e.disallowedTagsMode==="recursiveEscape"&&!an$1(E)||e.nestingLimit!=null&&y>=e.nestingLimit)&&(w=!0,E[y]=!0,(e.disallowedTagsMode==="discard"||e.disallowedTagsMode==="completelyDiscard")&&l.indexOf(h)!==-1&&(F=!0,S=1),E[y]=!0),y++,w){if(e.disallowedTagsMode==="discard"||e.disallowedTagsMode==="completelyDiscard")return;n=r,r="";}r+="<"+h,h==="script"&&(e.allowedScriptHostnames||e.allowedScriptDomains)&&(g.innerText=""),(!o||ie(o,h)||o["*"])&&Ae$1(m,function(P,L){if(!on$1.test(L)){delete g.attribs[L];return}if(P===""&&!e.allowedEmptyAttributes.includes(L)&&(e.nonBooleanAttributes.includes(L)||e.nonBooleanAttributes.includes("*"))){delete g.attribs[L];return}let Ye=!1;if(!o||ie(o,h)&&o[h].indexOf(L)!==-1||o["*"]&&o["*"].indexOf(L)!==-1||ie(d,h)&&d[h].test(L)||d["*"]&&d["*"].test(L))Ye=!0;else if(o&&o[h]){for(const I of o[h])if(en$1(I)&&I.name&&I.name===L){Ye=!0;let N="";if(I.multiple===!0){const le=P.split(" ");for(const ne of le)I.values.indexOf(ne)!==-1&&(N===""?N=ne:N+=" "+ne);}else I.values.indexOf(P)>=0&&(N=P);P=N;}}if(Ye){if(e.allowedSchemesAppliedToAttributes.indexOf(L)!==-1&&J(h,P)){delete g.attribs[L];return}if(h==="script"&&L==="src"){let I=!0;try{const N=Q(P);if(e.allowedScriptHostnames||e.allowedScriptDomains){const le=(e.allowedScriptHostnames||[]).find(function(ee){return ee===N.url.hostname}),ne=(e.allowedScriptDomains||[]).find(function(ee){return N.url.hostname===ee||N.url.hostname.endsWith(`.${ee}`)});I=le||ne;}}catch{I=!1;}if(!I){delete g.attribs[L];return}}if(h==="iframe"&&L==="src"){let I=!0;try{const N=Q(P);if(N.isRelativeUrl)I=ie(e,"allowIframeRelativeUrls")?e.allowIframeRelativeUrls:!e.allowedIframeHostnames&&!e.allowedIframeDomains;else if(e.allowedIframeHostnames||e.allowedIframeDomains){const le=(e.allowedIframeHostnames||[]).find(function(ee){return ee===N.url.hostname}),ne=(e.allowedIframeDomains||[]).find(function(ee){return N.url.hostname===ee||N.url.hostname.endsWith(`.${ee}`)});I=le||ne;}}catch{I=!1;}if(!I){delete g.attribs[L];return}}if(L==="srcset")try{let I=un$1(P);if(I.forEach(function(N){J("srcset",N.url)&&(N.evil=!0);}),I=$u(I,function(N){return !N.evil}),I.length)P=sn$1($u(I,function(N){return !N.evil})),g.attribs[L]=P;else {delete g.attribs[L];return}}catch{delete g.attribs[L];return}if(L==="class"){const I=f[h],N=f["*"],le=p[h],ne=s[h],ee=p["*"],vu=[le,ee].concat(ne).filter(function(Mt){return Mt});if(I&&N?P=k(P,Uu(I,N),vu):P=k(P,I||N,vu),!P.length){delete g.attribs[L];return}}if(L==="style"){if(e.parseStyleAttributes)try{const I=tn$1(h+" {"+P+"}",{map:!1}),N=b(I,e.allowedStyles);if(P=D(N),P.length===0){delete g.attribs[L];return}}catch{typeof window<"u"&&console.warn('Failed to parse "'+h+" {"+P+`}", If you're running this in a browser, we recommend to disable style parsing: options.parseStyleAttributes: false, since this only works in a node environment due to a postcss dependency, More info: https://github.com/apostrophecms/sanitize-html/issues/547`),delete g.attribs[L];return}else if(e.allowedStyles)throw new Error("allowedStyles option cannot be used together with parseStyleAttributes: false.")}r+=" "+L,P&&P.length?r+='="'+V(P,!0)+'"':e.allowedEmptyAttributes.includes(L)&&(r+='=""');}else delete g.attribs[L];}),e.selfClosing.indexOf(h)!==-1?r+=" />":(r+=">",g.innerText&&!j&&!e.textFilter&&(r+=V(g.innerText),_=!0)),w&&(r=n+V(r),n="");},ontext:function(h){if(F)return;const m=v[v.length-1];let g;if(m&&(g=m.tag,h=m.innerText!==void 0?m.innerText:h),e.disallowedTagsMode==="completelyDiscard"&&!i(g))h="";else if((e.disallowedTagsMode==="discard"||e.disallowedTagsMode==="completelyDiscard")&&(g==="script"||g==="style"))r+=h;else {const w=V(h,!1);e.textFilter&&!_?r+=e.textFilter(w,g):_||(r+=w);}if(v.length){const w=v[v.length-1];w.text+=h;}},onclosetag:function(h,m){if(F)if(S--,!S)F=!1;else return;const g=v.pop();if(!g)return;if(g.tag!==h){v.push(g);return}F=e.enforceHtmlBoundary?h==="html":!1,y--;const w=E[y];if(w){if(delete E[y],e.disallowedTagsMode==="discard"||e.disallowedTagsMode==="completelyDiscard"){g.updateParentNodeText();return}n=r,r="";}if(C[y]&&(h=C[y],delete C[y]),e.exclusiveFilter&&e.exclusiveFilter(g)){r=r.substr(0,g.tagPosition);return}if(g.updateParentNodeMediaChildren(),g.updateParentNodeText(),e.selfClosing.indexOf(h)!==-1||m&&!i(h)&&["escape","recursiveEscape"].indexOf(e.disallowedTagsMode)>=0){w&&(r=n,n="");return}r+="</"+h+">",w&&(r=n+V(r),n=""),_=!1;}},e.parser);return M.write(t),M.end(),r;function U(){r="",y=0,v=[],E={},C={},F=!1,S=0;}function V(h,m){return typeof h!="string"&&(h=h+""),e.parser.decodeEntities&&(h=h.replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;"),m&&(h=h.replace(/"/g,"&quot;"))),h=h.replace(/&(?![a-zA-Z0-9#]{1,20};)/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;"),m&&(h=h.replace(/"/g,"&quot;")),h}function J(h,m){for(m=m.replace(/[\x00-\x20]+/g,"");;){const j=m.indexOf("<!--");if(j===-1)break;const H=m.indexOf("-->",j+4);if(H===-1)break;m=m.substring(0,j)+m.substring(H+3);}const g=m.match(/^([a-zA-Z][a-zA-Z0-9.\-+]*):/);if(!g)return m.match(/^[/\\]{2}/)?!e.allowProtocolRelative:!1;const w=g[1].toLowerCase();return ie(e.allowedSchemesByTag,h)?e.allowedSchemesByTag[h].indexOf(w)===-1:!e.allowedSchemes||e.allowedSchemes.indexOf(w)===-1}function Q(h){if(h=h.replace(/^(\w+:)?\s*[\\/]\s*[\\/]/,"$1//"),h.startsWith("relative:"))throw new Error("relative: exploit attempt");let m="relative://relative-site";for(let j=0;j<100;j++)m+=`/${j}`;const g=new URL(h,m);return {isRelativeUrl:g&&g.hostname==="relative-site"&&g.protocol==="relative:",url:g}}function b(h,m){if(!m)return h;const g=h.nodes[0];let w;return m[g.selector]&&m["*"]?w=Uu(m[g.selector],m["*"]):w=m[g.selector]||m["*"],w&&(h.nodes[0].nodes=g.nodes.reduce(A(w),[])),h}function D(h){return h.nodes[0].nodes.reduce(function(m,g){return m.push(`${g.prop}:${g.value}${g.important?" !important":""}`),m},[]).join(";")}function A(h){return function(m,g){return ie(h,g.prop)&&h[g.prop].some(function(j){return j.test(g.value)})&&m.push(g),m}}function k(h,m,g){return m?(h=h.split(/\s+/),h.filter(function(w){return m.indexOf(w)!==-1||g.some(function(j){return j.test(w)})}).join(" ")):h}}const ln$1={decodeEntities:!0};Fe.defaults={allowedTags:["address","article","aside","footer","header","h1","h2","h3","h4","h5","h6","hgroup","main","nav","section","blockquote","dd","div","dl","dt","figcaption","figure","hr","li","main","ol","p","pre","ul","a","abbr","b","bdi","bdo","br","cite","code","data","dfn","em","i","kbd","mark","q","rb","rp","rt","rtc","ruby","s","samp","small","span","strong","sub","sup","time","u","var","wbr","caption","col","colgroup","table","tbody","td","tfoot","th","thead","tr"],nonBooleanAttributes:["abbr","accept","accept-charset","accesskey","action","allow","alt","as","autocapitalize","autocomplete","blocking","charset","cite","class","color","cols","colspan","content","contenteditable","coords","crossorigin","data","datetime","decoding","dir","dirname","download","draggable","enctype","enterkeyhint","fetchpriority","for","form","formaction","formenctype","formmethod","formtarget","headers","height","hidden","high","href","hreflang","http-equiv","id","imagesizes","imagesrcset","inputmode","integrity","is","itemid","itemprop","itemref","itemtype","kind","label","lang","list","loading","low","max","maxlength","media","method","min","minlength","name","nonce","optimum","pattern","ping","placeholder","popover","popovertarget","popovertargetaction","poster","preload","referrerpolicy","rel","rows","rowspan","sandbox","scope","shape","size","sizes","slot","span","spellcheck","src","srcdoc","srclang","srcset","start","step","style","tabindex","target","title","translate","type","usemap","value","width","wrap","onauxclick","onafterprint","onbeforematch","onbeforeprint","onbeforeunload","onbeforetoggle","onblur","oncancel","oncanplay","oncanplaythrough","onchange","onclick","onclose","oncontextlost","oncontextmenu","oncontextrestored","oncopy","oncuechange","oncut","ondblclick","ondrag","ondragend","ondragenter","ondragleave","ondragover","ondragstart","ondrop","ondurationchange","onemptied","onended","onerror","onfocus","onformdata","onhashchange","oninput","oninvalid","onkeydown","onkeypress","onkeyup","onlanguagechange","onload","onloadeddata","onloadedmetadata","onloadstart","onmessage","onmessageerror","onmousedown","onmouseenter","onmouseleave","onmousemove","onmouseout","onmouseover","onmouseup","onoffline","ononline","onpagehide","onpageshow","onpaste","onpause","onplay","onplaying","onpopstate","onprogress","onratechange","onreset","onresize","onrejectionhandled","onscroll","onscrollend","onsecuritypolicyviolation","onseeked","onseeking","onselect","onslotchange","onstalled","onstorage","onsubmit","onsuspend","ontimeupdate","ontoggle","onunhandledrejection","onunload","onvolumechange","onwaiting","onwheel"],disallowedTagsMode:"discard",allowedAttributes:{a:["href","name","target"],img:["src","srcset","alt","title","width","height","loading"]},allowedEmptyAttributes:["alt"],selfClosing:["img","br","hr","area","base","basefont","input","link","meta"],allowedSchemes:["http","https","ftp","mailto","tel"],allowedSchemesByTag:{},allowedSchemesAppliedToAttributes:["href","src","cite"],allowProtocolRelative:!0,enforceHtmlBoundary:!1,parseStyleAttributes:!0};Fe.simpleTransform=function(t,e,u){return u=u===void 0?!0:u,e=e||{},function(r,n){let a;if(u)for(a in e)n[a]=e[a];else n=e;return {tagName:t,attribs:n}}};const dn$1=Ir$1(cn$1);function Vu(t){return dn$1(t)}const Gu=["!--","!doctype","a","abbr","acronym","address","applet","area","article","aside","audio","b","base","basefont","bdi","bdo","big","blockquote","body","br","button","canvas","caption","center","cite","code","col","colgroup","data","datalist","dd","del","details","dfn","dialog","dir","div","dl","dt","em","embed","fieldset","figcaption","figure","font","footer","form","frame","frameset","h1","h2","h3","h4","h5","h6","head","header","hgroup","hr","html","i","iframe","img","input","ins","kbd","label","legend","li","link","main","map","mark","menu","meta","meter","nav","noframes","noscript","object","ol","optgroup","option","output","p","param","picture","pre","progress","q","rp","rt","ruby","s","samp","script","search","section","select","small","source","span","strike","strong","style","sub","summary","sup","svg","table","tbody","td","template","textarea","tfoot","th","thead","time","title","tr","track","tt","u","ul","var","video","wbr"],fn=["g","defs","use","symbol","rect","circle","ellipse","line","polyline","polygon","path","image","text","tspan","textPath","linearGradient","radialGradient","stop","pattern","clipPath","mask","filter","feBlend","feColorMatrix","feComponentTransfer","feComposite","feConvolveMatrix","feDiffuseLighting","feDisplacementMap","feGaussianBlur","feMerge","feMorphology","feOffset","feSpecularLighting","feTurbulence","feMergeNode","feFuncR","feFuncG","feFuncB","feFuncA","feDistantLight","fePointLight","feSpotLight","feFlood","feTile","animate","animateTransform","animateMotion","mpath","set","view","cursor","foreignObject","desc","title","metadata","switch"],hn=[...Gu,...fn.filter(t=>!Gu.includes(t))],bn={code:'span.svelte-7ddecg div[class*="code_wrap"]{position:relative}span.svelte-7ddecg span.katex{font-size:var(--text-lg);direction:ltr}span.svelte-7ddecg div[class*="code_wrap"] > button{z-index:1;cursor:pointer;border-bottom-left-radius:var(--radius-sm);padding:var(--spacing-md);width:25px;height:25px;position:absolute;right:0}span.svelte-7ddecg .check{opacity:0;z-index:var(--layer-top);transition:opacity 0.2s;background:var(--code-background-fill);color:var(--body-text-color);position:absolute;top:var(--size-1-5);left:var(--size-1-5)}span.svelte-7ddecg p:not(:first-child){margin-top:var(--spacing-xxl)}span.svelte-7ddecg .md-header-anchor{margin-left:-25px;padding-right:8px;line-height:1;color:var(--body-text-color-subdued);opacity:0}span.svelte-7ddecg h1:hover .md-header-anchor,span.svelte-7ddecg h2:hover .md-header-anchor,span.svelte-7ddecg h3:hover .md-header-anchor,span.svelte-7ddecg h4:hover .md-header-anchor,span.svelte-7ddecg h5:hover .md-header-anchor,span.svelte-7ddecg h6:hover .md-header-anchor{opacity:1}span.md.svelte-7ddecg .md-header-anchor > svg{color:var(--body-text-color-subdued)}span.svelte-7ddecg table{word-break:break-word}',map:'{"version":3,"file":"MarkdownCode.svelte","sources":["MarkdownCode.svelte"],"sourcesContent":["<script lang=\\"ts\\">import { afterUpdate, tick, onMount } from \\"svelte\\";\\nimport { create_marked } from \\"./utils\\";\\nimport { sanitize } from \\"@gradio/sanitize\\";\\nimport \\"./prism.css\\";\\nimport { standardHtmlAndSvgTags } from \\"./html-tags\\";\\nexport let chatbot = true;\\nexport let message;\\nexport let sanitize_html = true;\\nexport let latex_delimiters = [];\\nexport let render_markdown = true;\\nexport let line_breaks = true;\\nexport let header_links = false;\\nexport let allow_tags = false;\\nexport let theme_mode = \\"system\\";\\nlet el;\\nlet html;\\nlet katex_loaded = false;\\nconst marked = create_marked({\\n    header_links,\\n    line_breaks,\\n    latex_delimiters: latex_delimiters || []\\n});\\nfunction has_math_syntax(text) {\\n    if (!latex_delimiters || latex_delimiters.length === 0) {\\n        return false;\\n    }\\n    return latex_delimiters.some((delimiter) => text.includes(delimiter.left) && text.includes(delimiter.right));\\n}\\nfunction escapeRegExp(string) {\\n    return string.replace(/[.*+?^${}()|[\\\\]\\\\\\\\]/g, \\"\\\\\\\\$&\\");\\n}\\nfunction escapeTags(content, tagsToEscape) {\\n    if (tagsToEscape === true) {\\n        const tagRegex = /<\\\\/?([a-zA-Z][a-zA-Z0-9-]*)([\\\\s>])/g;\\n        return content.replace(tagRegex, (match, tagName, endChar) => {\\n            if (!standardHtmlAndSvgTags.includes(tagName.toLowerCase())) {\\n                return match.replace(/</g, \\"&lt;\\").replace(/>/g, \\"&gt;\\");\\n            }\\n            return match;\\n        });\\n    }\\n    if (Array.isArray(tagsToEscape)) {\\n        const tagPattern = tagsToEscape.map((tag) => ({\\n            open: new RegExp(`<(${tag})(\\\\\\\\s+[^>]*)?>`, \\"gi\\"),\\n            close: new RegExp(`</(${tag})>`, \\"gi\\")\\n        }));\\n        let result = content;\\n        tagPattern.forEach((pattern) => {\\n            result = result.replace(pattern.open, (match) => match.replace(/</g, \\"&lt;\\").replace(/>/g, \\"&gt;\\"));\\n            result = result.replace(pattern.close, (match) => match.replace(/</g, \\"&lt;\\").replace(/>/g, \\"&gt;\\"));\\n        });\\n        return result;\\n    }\\n    return content;\\n}\\nfunction process_message(value) {\\n    let parsedValue = value;\\n    if (render_markdown) {\\n        const latexBlocks = [];\\n        latex_delimiters.forEach((delimiter, index) => {\\n            const leftDelimiter = escapeRegExp(delimiter.left);\\n            const rightDelimiter = escapeRegExp(delimiter.right);\\n            const regex = new RegExp(`${leftDelimiter}([\\\\\\\\s\\\\\\\\S]+?)${rightDelimiter}`, \\"g\\");\\n            parsedValue = parsedValue.replace(regex, (match, p1) => {\\n                latexBlocks.push(match);\\n                return `%%%LATEX_BLOCK_${latexBlocks.length - 1}%%%`;\\n            });\\n        });\\n        parsedValue = marked.parse(parsedValue);\\n        parsedValue = parsedValue.replace(/%%%LATEX_BLOCK_(\\\\d+)%%%/g, (match, p1) => latexBlocks[parseInt(p1, 10)]);\\n    }\\n    if (allow_tags) {\\n        parsedValue = escapeTags(parsedValue, allow_tags);\\n    }\\n    if (sanitize_html && sanitize) {\\n        parsedValue = sanitize(parsedValue);\\n    }\\n    return parsedValue;\\n}\\n$: if (message && message.trim()) {\\n    html = process_message(message);\\n}\\nelse {\\n    html = \\"\\";\\n}\\nasync function render_html(value) {\\n    if (latex_delimiters.length > 0 && value && has_math_syntax(value)) {\\n        if (!katex_loaded) {\\n            await Promise.all([\\n                import(\\"katex/dist/katex.min.css\\"),\\n                import(\\"katex/contrib/auto-render\\")\\n            ]).then(([, { default: render_math_in_element }]) => {\\n                katex_loaded = true;\\n                render_math_in_element(el, {\\n                    delimiters: latex_delimiters,\\n                    throwOnError: false\\n                });\\n            });\\n        }\\n        else {\\n            const { default: render_math_in_element } = await import(\\"katex/contrib/auto-render\\");\\n            render_math_in_element(el, {\\n                delimiters: latex_delimiters,\\n                throwOnError: false\\n            });\\n        }\\n    }\\n    if (el) {\\n        const mermaidDivs = el.querySelectorAll(\\".mermaid\\");\\n        if (mermaidDivs.length > 0) {\\n            await tick();\\n            const { default: mermaid } = await import(\\"mermaid\\");\\n            mermaid.initialize({\\n                startOnLoad: false,\\n                theme: theme_mode === \\"dark\\" ? \\"dark\\" : \\"default\\",\\n                securityLevel: \\"antiscript\\"\\n            });\\n            await mermaid.run({\\n                nodes: Array.from(mermaidDivs).map((node) => node)\\n            });\\n        }\\n    }\\n}\\nafterUpdate(async () => {\\n    if (el && document.body.contains(el)) {\\n        await render_html(message);\\n    }\\n    else {\\n        console.error(\\"Element is not in the DOM\\");\\n    }\\n});\\n<\/script>\\n\\n<span class:chatbot bind:this={el} class=\\"md\\" class:prose={render_markdown}>\\n\\t{@html html}\\n</span>\\n\\n<style>\\n\\tspan :global(div[class*=\\"code_wrap\\"]) {\\n\\t\\tposition: relative;\\n\\t}\\n\\n\\t/* KaTeX */\\n\\tspan :global(span.katex) {\\n\\t\\tfont-size: var(--text-lg);\\n\\t\\tdirection: ltr;\\n\\t}\\n\\n\\tspan :global(div[class*=\\"code_wrap\\"] > button) {\\n\\t\\tz-index: 1;\\n\\t\\tcursor: pointer;\\n\\t\\tborder-bottom-left-radius: var(--radius-sm);\\n\\t\\tpadding: var(--spacing-md);\\n\\t\\twidth: 25px;\\n\\t\\theight: 25px;\\n\\t\\tposition: absolute;\\n\\t\\tright: 0;\\n\\t}\\n\\n\\tspan :global(.check) {\\n\\t\\topacity: 0;\\n\\t\\tz-index: var(--layer-top);\\n\\t\\ttransition: opacity 0.2s;\\n\\t\\tbackground: var(--code-background-fill);\\n\\t\\tcolor: var(--body-text-color);\\n\\t\\tposition: absolute;\\n\\t\\ttop: var(--size-1-5);\\n\\t\\tleft: var(--size-1-5);\\n\\t}\\n\\n\\tspan :global(p:not(:first-child)) {\\n\\t\\tmargin-top: var(--spacing-xxl);\\n\\t}\\n\\n\\tspan :global(.md-header-anchor) {\\n\\t\\t/* position: absolute; */\\n\\t\\tmargin-left: -25px;\\n\\t\\tpadding-right: 8px;\\n\\t\\tline-height: 1;\\n\\t\\tcolor: var(--body-text-color-subdued);\\n\\t\\topacity: 0;\\n\\t}\\n\\n\\tspan :global(h1:hover .md-header-anchor),\\n\\tspan :global(h2:hover .md-header-anchor),\\n\\tspan :global(h3:hover .md-header-anchor),\\n\\tspan :global(h4:hover .md-header-anchor),\\n\\tspan :global(h5:hover .md-header-anchor),\\n\\tspan :global(h6:hover .md-header-anchor) {\\n\\t\\topacity: 1;\\n\\t}\\n\\n\\tspan.md :global(.md-header-anchor > svg) {\\n\\t\\tcolor: var(--body-text-color-subdued);\\n\\t}\\n\\n\\tspan :global(table) {\\n\\t\\tword-break: break-word;\\n\\t}</style>\\n"],"names":[],"mappings":"AA0IC,kBAAI,CAAS,uBAAyB,CACrC,QAAQ,CAAE,QACX,CAGA,kBAAI,CAAS,UAAY,CACxB,SAAS,CAAE,IAAI,SAAS,CAAC,CACzB,SAAS,CAAE,GACZ,CAEA,kBAAI,CAAS,gCAAkC,CAC9C,OAAO,CAAE,CAAC,CACV,MAAM,CAAE,OAAO,CACf,yBAAyB,CAAE,IAAI,WAAW,CAAC,CAC3C,OAAO,CAAE,IAAI,YAAY,CAAC,CAC1B,KAAK,CAAE,IAAI,CACX,MAAM,CAAE,IAAI,CACZ,QAAQ,CAAE,QAAQ,CAClB,KAAK,CAAE,CACR,CAEA,kBAAI,CAAS,MAAQ,CACpB,OAAO,CAAE,CAAC,CACV,OAAO,CAAE,IAAI,WAAW,CAAC,CACzB,UAAU,CAAE,OAAO,CAAC,IAAI,CACxB,UAAU,CAAE,IAAI,sBAAsB,CAAC,CACvC,KAAK,CAAE,IAAI,iBAAiB,CAAC,CAC7B,QAAQ,CAAE,QAAQ,CAClB,GAAG,CAAE,IAAI,UAAU,CAAC,CACpB,IAAI,CAAE,IAAI,UAAU,CACrB,CAEA,kBAAI,CAAS,mBAAqB,CACjC,UAAU,CAAE,IAAI,aAAa,CAC9B,CAEA,kBAAI,CAAS,iBAAmB,CAE/B,WAAW,CAAE,KAAK,CAClB,aAAa,CAAE,GAAG,CAClB,WAAW,CAAE,CAAC,CACd,KAAK,CAAE,IAAI,yBAAyB,CAAC,CACrC,OAAO,CAAE,CACV,CAEA,kBAAI,CAAS,0BAA2B,CACxC,kBAAI,CAAS,0BAA2B,CACxC,kBAAI,CAAS,0BAA2B,CACxC,kBAAI,CAAS,0BAA2B,CACxC,kBAAI,CAAS,0BAA2B,CACxC,kBAAI,CAAS,0BAA4B,CACxC,OAAO,CAAE,CACV,CAEA,IAAI,iBAAG,CAAS,uBAAyB,CACxC,KAAK,CAAE,IAAI,yBAAyB,CACrC,CAEA,kBAAI,CAAS,KAAO,CACnB,UAAU,CAAE,UACb"}'};function Zu(t){return t.replace(/[.*+?^${}()|[\]\\]/g,"\\$&")}const An=create_ssr_component((t,e,u,r)=>{let{chatbot:n=!0}=e,{message:a}=e,{sanitize_html:i=!0}=e,{latex_delimiters:l=[]}=e,{render_markdown:o=!0}=e,{line_breaks:d=!0}=e,{header_links:f=!1}=e,{allow_tags:p=!1}=e,{theme_mode:s="system"}=e,c,x;const y=V0({header_links:f,line_breaks:d,latex_delimiters:l||[]});function v(C,F){if(F===!0){const S=/<\/?([a-zA-Z][a-zA-Z0-9-]*)([\s>])/g;return C.replace(S,(_,M,U)=>hn.includes(M.toLowerCase())?_:_.replace(/</g,"&lt;").replace(/>/g,"&gt;"))}if(Array.isArray(F)){const S=F.map(M=>({open:new RegExp(`<(${M})(\\s+[^>]*)?>`,"gi"),close:new RegExp(`</(${M})>`,"gi")}));let _=C;return S.forEach(M=>{_=_.replace(M.open,U=>U.replace(/</g,"&lt;").replace(/>/g,"&gt;")),_=_.replace(M.close,U=>U.replace(/</g,"&lt;").replace(/>/g,"&gt;"));}),_}return C}function E(C){let F=C;if(o){const S=[];l.forEach((_,M)=>{const U=Zu(_.left),V=Zu(_.right),J=new RegExp(`${U}([\\s\\S]+?)${V}`,"g");F=F.replace(J,(Q,b)=>(S.push(Q),`%%%LATEX_BLOCK_${S.length-1}%%%`));}),F=y.parse(F),F=F.replace(/%%%LATEX_BLOCK_(\d+)%%%/g,(_,M)=>S[parseInt(M,10)]);}return p&&(F=v(F,p)),i&&Vu&&(F=Vu(F)),F}return e.chatbot===void 0&&u.chatbot&&n!==void 0&&u.chatbot(n),e.message===void 0&&u.message&&a!==void 0&&u.message(a),e.sanitize_html===void 0&&u.sanitize_html&&i!==void 0&&u.sanitize_html(i),e.latex_delimiters===void 0&&u.latex_delimiters&&l!==void 0&&u.latex_delimiters(l),e.render_markdown===void 0&&u.render_markdown&&o!==void 0&&u.render_markdown(o),e.line_breaks===void 0&&u.line_breaks&&d!==void 0&&u.line_breaks(d),e.header_links===void 0&&u.header_links&&f!==void 0&&u.header_links(f),e.allow_tags===void 0&&u.allow_tags&&p!==void 0&&u.allow_tags(p),e.theme_mode===void 0&&u.theme_mode&&s!==void 0&&u.theme_mode(s),t.css.add(bn),a&&a.trim()?x=E(a):x="",`<span class="${["md svelte-7ddecg",(n?"chatbot":"")+" "+(o?"prose":"")].join(" ").trim()}"${add_attribute("this",c,0)}><!-- HTML_TAG_START -->${x}<!-- HTML_TAG_END --> </span>`});

const P={code:".block.svelte-1svsvh2{position:relative;margin:0;box-shadow:var(--block-shadow);border-width:var(--block-border-width);border-color:var(--block-border-color);border-radius:var(--block-radius);background:var(--block-background-fill);width:100%;line-height:var(--line-sm)}.block.fullscreen.svelte-1svsvh2{border-radius:0}.auto-margin.svelte-1svsvh2{margin-left:auto;margin-right:auto}.block.border_focus.svelte-1svsvh2{border-color:var(--color-accent)}.block.border_contrast.svelte-1svsvh2{border-color:var(--body-text-color)}.padded.svelte-1svsvh2{padding:var(--block-padding)}.hidden.svelte-1svsvh2{display:none}.flex.svelte-1svsvh2{display:flex;flex-direction:column}.hide-container.svelte-1svsvh2:not(.fullscreen){margin:0;box-shadow:none;--block-border-width:0;background:transparent;padding:0;overflow:visible}.resize-handle.svelte-1svsvh2{position:absolute;bottom:0;right:0;width:10px;height:10px;fill:var(--block-border-color);cursor:nwse-resize}.fullscreen.svelte-1svsvh2{position:fixed;top:0;left:0;width:100vw;height:100vh;z-index:1000;overflow:auto}.animating.svelte-1svsvh2{animation:svelte-1svsvh2-pop-out 0.1s ease-out forwards}@keyframes svelte-1svsvh2-pop-out{0%{position:fixed;top:var(--start-top);left:var(--start-left);width:var(--start-width);height:var(--start-height);z-index:100}100%{position:fixed;top:0vh;left:0vw;width:100vw;height:100vh;z-index:1000}}.placeholder.svelte-1svsvh2{border-radius:var(--block-radius);border-width:var(--block-border-width);border-color:var(--block-border-color);border-style:dashed}",map:'{"version":3,"file":"Block.svelte","sources":["Block.svelte"],"sourcesContent":["<script lang=\\"ts\\">export let height = void 0;\\nexport let min_height = void 0;\\nexport let max_height = void 0;\\nexport let width = void 0;\\nexport let elem_id = \\"\\";\\nexport let elem_classes = [];\\nexport let variant = \\"solid\\";\\nexport let border_mode = \\"base\\";\\nexport let padding = true;\\nexport let type = \\"normal\\";\\nexport let test_id = void 0;\\nexport let explicit_call = false;\\nexport let container = true;\\nexport let visible = true;\\nexport let allow_overflow = true;\\nexport let overflow_behavior = \\"auto\\";\\nexport let scale = null;\\nexport let min_width = 0;\\nexport let flex = false;\\nexport let resizable = false;\\nexport let rtl = false;\\nexport let fullscreen = false;\\nlet old_fullscreen = fullscreen;\\nlet element;\\nlet tag = type === \\"fieldset\\" ? \\"fieldset\\" : \\"div\\";\\nlet placeholder_height = 0;\\nlet placeholder_width = 0;\\nlet preexpansionBoundingRect = null;\\nfunction handleKeydown(event) {\\n    if (fullscreen && event.key === \\"Escape\\") {\\n        fullscreen = false;\\n    }\\n}\\n$: if (fullscreen !== old_fullscreen) {\\n    old_fullscreen = fullscreen;\\n    if (fullscreen) {\\n        preexpansionBoundingRect = element.getBoundingClientRect();\\n        placeholder_height = element.offsetHeight;\\n        placeholder_width = element.offsetWidth;\\n        window.addEventListener(\\"keydown\\", handleKeydown);\\n    }\\n    else {\\n        preexpansionBoundingRect = null;\\n        window.removeEventListener(\\"keydown\\", handleKeydown);\\n    }\\n}\\nconst get_dimension = (dimension_value) => {\\n    if (dimension_value === void 0) {\\n        return void 0;\\n    }\\n    if (typeof dimension_value === \\"number\\") {\\n        return dimension_value + \\"px\\";\\n    }\\n    else if (typeof dimension_value === \\"string\\") {\\n        return dimension_value;\\n    }\\n};\\n$: if (!visible) {\\n    flex = false;\\n}\\nconst resize = (e) => {\\n    let prevY = e.clientY;\\n    const onMouseMove = (e2) => {\\n        const dy = e2.clientY - prevY;\\n        prevY = e2.clientY;\\n        element.style.height = `${element.offsetHeight + dy}px`;\\n    };\\n    const onMouseUp = () => {\\n        window.removeEventListener(\\"mousemove\\", onMouseMove);\\n        window.removeEventListener(\\"mouseup\\", onMouseUp);\\n    };\\n    window.addEventListener(\\"mousemove\\", onMouseMove);\\n    window.addEventListener(\\"mouseup\\", onMouseUp);\\n};\\n<\/script>\\n\\n<svelte:element\\n\\tthis={tag}\\n\\tbind:this={element}\\n\\tdata-testid={test_id}\\n\\tid={elem_id}\\n\\tclass:hidden={visible === false}\\n\\tclass=\\"block {elem_classes?.join(\' \') || \'\'}\\"\\n\\tclass:padded={padding}\\n\\tclass:flex\\n\\tclass:border_focus={border_mode === \\"focus\\"}\\n\\tclass:border_contrast={border_mode === \\"contrast\\"}\\n\\tclass:hide-container={!explicit_call && !container}\\n\\tstyle:height={fullscreen ? undefined : get_dimension(height)}\\n\\tstyle:min-height={fullscreen ? undefined : get_dimension(min_height)}\\n\\tstyle:max-height={fullscreen ? undefined : get_dimension(max_height)}\\n\\tclass:fullscreen\\n\\tclass:animating={fullscreen && preexpansionBoundingRect !== null}\\n\\tstyle:--start-top={preexpansionBoundingRect\\n\\t\\t? `${preexpansionBoundingRect.top}px`\\n\\t\\t: \\"0px\\"}\\n\\tstyle:--start-left={preexpansionBoundingRect\\n\\t\\t? `${preexpansionBoundingRect.left}px`\\n\\t\\t: \\"0px\\"}\\n\\tstyle:--start-width={preexpansionBoundingRect\\n\\t\\t? `${preexpansionBoundingRect.width}px`\\n\\t\\t: \\"0px\\"}\\n\\tstyle:--start-height={preexpansionBoundingRect\\n\\t\\t? `${preexpansionBoundingRect.height}px`\\n\\t\\t: \\"0px\\"}\\n\\tstyle:width={fullscreen\\n\\t\\t? undefined\\n\\t\\t: typeof width === \\"number\\"\\n\\t\\t\\t? `calc(min(${width}px, 100%))`\\n\\t\\t\\t: get_dimension(width)}\\n\\tstyle:border-style={variant}\\n\\tstyle:overflow={allow_overflow ? overflow_behavior : \\"hidden\\"}\\n\\tstyle:flex-grow={scale}\\n\\tstyle:min-width={`calc(min(${min_width}px, 100%))`}\\n\\tstyle:border-width=\\"var(--block-border-width)\\"\\n\\tclass:auto-margin={scale === null}\\n\\tdir={rtl ? \\"rtl\\" : \\"ltr\\"}\\n>\\n\\t<slot />\\n\\t{#if resizable}\\n\\t\\t<!-- svelte-ignore a11y-no-static-element-interactions -->\\n\\t\\t<svg\\n\\t\\t\\tclass=\\"resize-handle\\"\\n\\t\\t\\txmlns=\\"http://www.w3.org/2000/svg\\"\\n\\t\\t\\tviewBox=\\"0 0 10 10\\"\\n\\t\\t\\ton:mousedown={resize}\\n\\t\\t>\\n\\t\\t\\t<line x1=\\"1\\" y1=\\"9\\" x2=\\"9\\" y2=\\"1\\" stroke=\\"gray\\" stroke-width=\\"0.5\\" />\\n\\t\\t\\t<line x1=\\"5\\" y1=\\"9\\" x2=\\"9\\" y2=\\"5\\" stroke=\\"gray\\" stroke-width=\\"0.5\\" />\\n\\t\\t</svg>\\n\\t{/if}\\n</svelte:element>\\n{#if fullscreen}\\n\\t<div\\n\\t\\tclass=\\"placeholder\\"\\n\\t\\tstyle:height={placeholder_height + \\"px\\"}\\n\\t\\tstyle:width={placeholder_width + \\"px\\"}\\n\\t></div>\\n{/if}\\n\\n<style>\\n\\t.block {\\n\\t\\tposition: relative;\\n\\t\\tmargin: 0;\\n\\t\\tbox-shadow: var(--block-shadow);\\n\\t\\tborder-width: var(--block-border-width);\\n\\t\\tborder-color: var(--block-border-color);\\n\\t\\tborder-radius: var(--block-radius);\\n\\t\\tbackground: var(--block-background-fill);\\n\\t\\twidth: 100%;\\n\\t\\tline-height: var(--line-sm);\\n\\t}\\n\\t.block.fullscreen {\\n\\t\\tborder-radius: 0;\\n\\t}\\n\\n\\t.auto-margin {\\n\\t\\tmargin-left: auto;\\n\\t\\tmargin-right: auto;\\n\\t}\\n\\n\\t.block.border_focus {\\n\\t\\tborder-color: var(--color-accent);\\n\\t}\\n\\n\\t.block.border_contrast {\\n\\t\\tborder-color: var(--body-text-color);\\n\\t}\\n\\n\\t.padded {\\n\\t\\tpadding: var(--block-padding);\\n\\t}\\n\\n\\t.hidden {\\n\\t\\tdisplay: none;\\n\\t}\\n\\n\\t.flex {\\n\\t\\tdisplay: flex;\\n\\t\\tflex-direction: column;\\n\\t}\\n\\t.hide-container:not(.fullscreen) {\\n\\t\\tmargin: 0;\\n\\t\\tbox-shadow: none;\\n\\t\\t--block-border-width: 0;\\n\\t\\tbackground: transparent;\\n\\t\\tpadding: 0;\\n\\t\\toverflow: visible;\\n\\t}\\n\\t.resize-handle {\\n\\t\\tposition: absolute;\\n\\t\\tbottom: 0;\\n\\t\\tright: 0;\\n\\t\\twidth: 10px;\\n\\t\\theight: 10px;\\n\\t\\tfill: var(--block-border-color);\\n\\t\\tcursor: nwse-resize;\\n\\t}\\n\\t.fullscreen {\\n\\t\\tposition: fixed;\\n\\t\\ttop: 0;\\n\\t\\tleft: 0;\\n\\t\\twidth: 100vw;\\n\\t\\theight: 100vh;\\n\\t\\tz-index: 1000;\\n\\t\\toverflow: auto;\\n\\t}\\n\\n\\t.animating {\\n\\t\\tanimation: pop-out 0.1s ease-out forwards;\\n\\t}\\n\\n\\t@keyframes pop-out {\\n\\t\\t0% {\\n\\t\\t\\tposition: fixed;\\n\\t\\t\\ttop: var(--start-top);\\n\\t\\t\\tleft: var(--start-left);\\n\\t\\t\\twidth: var(--start-width);\\n\\t\\t\\theight: var(--start-height);\\n\\t\\t\\tz-index: 100;\\n\\t\\t}\\n\\t\\t100% {\\n\\t\\t\\tposition: fixed;\\n\\t\\t\\ttop: 0vh;\\n\\t\\t\\tleft: 0vw;\\n\\t\\t\\twidth: 100vw;\\n\\t\\t\\theight: 100vh;\\n\\t\\t\\tz-index: 1000;\\n\\t\\t}\\n\\t}\\n\\n\\t.placeholder {\\n\\t\\tborder-radius: var(--block-radius);\\n\\t\\tborder-width: var(--block-border-width);\\n\\t\\tborder-color: var(--block-border-color);\\n\\t\\tborder-style: dashed;\\n\\t}</style>\\n"],"names":[],"mappings":"AA6IC,qBAAO,CACN,QAAQ,CAAE,QAAQ,CAClB,MAAM,CAAE,CAAC,CACT,UAAU,CAAE,IAAI,cAAc,CAAC,CAC/B,YAAY,CAAE,IAAI,oBAAoB,CAAC,CACvC,YAAY,CAAE,IAAI,oBAAoB,CAAC,CACvC,aAAa,CAAE,IAAI,cAAc,CAAC,CAClC,UAAU,CAAE,IAAI,uBAAuB,CAAC,CACxC,KAAK,CAAE,IAAI,CACX,WAAW,CAAE,IAAI,SAAS,CAC3B,CACA,MAAM,0BAAY,CACjB,aAAa,CAAE,CAChB,CAEA,2BAAa,CACZ,WAAW,CAAE,IAAI,CACjB,YAAY,CAAE,IACf,CAEA,MAAM,4BAAc,CACnB,YAAY,CAAE,IAAI,cAAc,CACjC,CAEA,MAAM,+BAAiB,CACtB,YAAY,CAAE,IAAI,iBAAiB,CACpC,CAEA,sBAAQ,CACP,OAAO,CAAE,IAAI,eAAe,CAC7B,CAEA,sBAAQ,CACP,OAAO,CAAE,IACV,CAEA,oBAAM,CACL,OAAO,CAAE,IAAI,CACb,cAAc,CAAE,MACjB,CACA,8BAAe,KAAK,WAAW,CAAE,CAChC,MAAM,CAAE,CAAC,CACT,UAAU,CAAE,IAAI,CAChB,oBAAoB,CAAE,CAAC,CACvB,UAAU,CAAE,WAAW,CACvB,OAAO,CAAE,CAAC,CACV,QAAQ,CAAE,OACX,CACA,6BAAe,CACd,QAAQ,CAAE,QAAQ,CAClB,MAAM,CAAE,CAAC,CACT,KAAK,CAAE,CAAC,CACR,KAAK,CAAE,IAAI,CACX,MAAM,CAAE,IAAI,CACZ,IAAI,CAAE,IAAI,oBAAoB,CAAC,CAC/B,MAAM,CAAE,WACT,CACA,0BAAY,CACX,QAAQ,CAAE,KAAK,CACf,GAAG,CAAE,CAAC,CACN,IAAI,CAAE,CAAC,CACP,KAAK,CAAE,KAAK,CACZ,MAAM,CAAE,KAAK,CACb,OAAO,CAAE,IAAI,CACb,QAAQ,CAAE,IACX,CAEA,yBAAW,CACV,SAAS,CAAE,sBAAO,CAAC,IAAI,CAAC,QAAQ,CAAC,QAClC,CAEA,WAAW,sBAAQ,CAClB,EAAG,CACF,QAAQ,CAAE,KAAK,CACf,GAAG,CAAE,IAAI,WAAW,CAAC,CACrB,IAAI,CAAE,IAAI,YAAY,CAAC,CACvB,KAAK,CAAE,IAAI,aAAa,CAAC,CACzB,MAAM,CAAE,IAAI,cAAc,CAAC,CAC3B,OAAO,CAAE,GACV,CACA,IAAK,CACJ,QAAQ,CAAE,KAAK,CACf,GAAG,CAAE,GAAG,CACR,IAAI,CAAE,GAAG,CACT,KAAK,CAAE,KAAK,CACZ,MAAM,CAAE,KAAK,CACb,OAAO,CAAE,IACV,CACD,CAEA,2BAAa,CACZ,aAAa,CAAE,IAAI,cAAc,CAAC,CAClC,YAAY,CAAE,IAAI,oBAAoB,CAAC,CACvC,YAAY,CAAE,IAAI,oBAAoB,CAAC,CACvC,YAAY,CAAE,MACf"}'},mt=create_ssr_component((o,t,e,n)=>{let{height:l=void 0}=t,{min_height:A=void 0}=t,{max_height:i=void 0}=t,{width:s=void 0}=t,{elem_id:a=""}=t,{elem_classes:d=[]}=t,{variant:g="solid"}=t,{border_mode:h="base"}=t,{padding:p=!0}=t,{type:m="normal"}=t,{test_id:x=void 0}=t,{explicit_call:b=!1}=t,{container:k=!0}=t,{visible:B=!0}=t,{allow_overflow:_=!0}=t,{overflow_behavior:z="auto"}=t,{scale:I=null}=t,{min_width:K=0}=t,{flex:y=!1}=t,{resizable:L=!1}=t,{rtl:W=!1}=t,{fullscreen:C=!1}=t,O=C,E,Z=m==="fieldset"?"fieldset":"div",G=0,U=0,w=null;function V(u){C&&u.key==="Escape"&&(C=!1);}const M=u=>{if(u!==void 0){if(typeof u=="number")return u+"px";if(typeof u=="string")return u}};return t.height===void 0&&e.height&&l!==void 0&&e.height(l),t.min_height===void 0&&e.min_height&&A!==void 0&&e.min_height(A),t.max_height===void 0&&e.max_height&&i!==void 0&&e.max_height(i),t.width===void 0&&e.width&&s!==void 0&&e.width(s),t.elem_id===void 0&&e.elem_id&&a!==void 0&&e.elem_id(a),t.elem_classes===void 0&&e.elem_classes&&d!==void 0&&e.elem_classes(d),t.variant===void 0&&e.variant&&g!==void 0&&e.variant(g),t.border_mode===void 0&&e.border_mode&&h!==void 0&&e.border_mode(h),t.padding===void 0&&e.padding&&p!==void 0&&e.padding(p),t.type===void 0&&e.type&&m!==void 0&&e.type(m),t.test_id===void 0&&e.test_id&&x!==void 0&&e.test_id(x),t.explicit_call===void 0&&e.explicit_call&&b!==void 0&&e.explicit_call(b),t.container===void 0&&e.container&&k!==void 0&&e.container(k),t.visible===void 0&&e.visible&&B!==void 0&&e.visible(B),t.allow_overflow===void 0&&e.allow_overflow&&_!==void 0&&e.allow_overflow(_),t.overflow_behavior===void 0&&e.overflow_behavior&&z!==void 0&&e.overflow_behavior(z),t.scale===void 0&&e.scale&&I!==void 0&&e.scale(I),t.min_width===void 0&&e.min_width&&K!==void 0&&e.min_width(K),t.flex===void 0&&e.flex&&y!==void 0&&e.flex(y),t.resizable===void 0&&e.resizable&&L!==void 0&&e.resizable(L),t.rtl===void 0&&e.rtl&&W!==void 0&&e.rtl(W),t.fullscreen===void 0&&e.fullscreen&&C!==void 0&&e.fullscreen(C),o.css.add(P),C!==O&&(O=C,C?(w=E.getBoundingClientRect(),G=E.offsetHeight,U=E.offsetWidth,window.addEventListener("keydown",V)):(w=null,window.removeEventListener("keydown",V))),B||(y=!1),`${(u=>u?`<${Z}${add_attribute("data-testid",x,0)}${add_attribute("id",a,0)} class="${["block "+escape(d?.join(" ")||"",!0)+" svelte-1svsvh2",(B===!1?"hidden":"")+" "+(p?"padded":"")+" "+(y?"flex":"")+" "+(h==="focus"?"border_focus":"")+" "+(h==="contrast"?"border_contrast":"")+" "+(!b&&!k?"hide-container":"")+" "+(C?"fullscreen":"")+" "+(C&&w!==null?"animating":"")+" "+(I===null?"auto-margin":"")].join(" ").trim()}"${add_attribute("dir",W?"rtl":"ltr",0)}${add_styles({height:C?void 0:M(l),"min-height":C?void 0:M(A),"max-height":C?void 0:M(i),"--start-top":w?`${w.top}px`:"0px","--start-left":w?`${w.left}px`:"0px","--start-width":w?`${w.width}px`:"0px","--start-height":w?`${w.height}px`:"0px",width:C?void 0:typeof s=="number"?`calc(min(${s}px, 100%))`:M(s),"border-style":g,overflow:_?z:"hidden","flex-grow":I,"min-width":`calc(min(${K}px, 100%))`,"border-width":"var(--block-border-width)"})}${add_attribute("this",E,0)}>${is_void(u)?"":`${n.default?n.default({}):""} ${L?' <svg class="resize-handle svelte-1svsvh2" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><line x1="1" y1="9" x2="9" y2="1" stroke="gray" stroke-width="0.5"></line><line x1="5" y1="9" x2="9" y2="5" stroke="gray" stroke-width="0.5"></line></svg>':""}`}${is_void(u)?"":`</${u}>`}`:"")(Z)} ${C?`<div class="placeholder svelte-1svsvh2"${add_styles({height:G+"px",width:U+"px"})}></div>`:""}`}),D={code:"div.svelte-j9uq24>.md.prose{font-weight:var(--block-info-text-weight);font-size:var(--block-info-text-size);line-height:var(--line-sm)}div.svelte-j9uq24>.md.prose *{color:var(--block-info-text-color)}div.svelte-j9uq24{margin-bottom:var(--spacing-md)}",map:'{"version":3,"file":"Info.svelte","sources":["Info.svelte"],"sourcesContent":["<script lang=\\"ts\\">import { MarkdownCode as Markdown } from \\"@gradio/markdown-code\\";\\nexport let info;\\n<\/script>\\n\\n<div>\\n\\t<Markdown message={info} sanitize_html={true} />\\n</div>\\n\\n<style>\\n\\tdiv > :global(.md.prose) {\\n\\t\\tfont-weight: var(--block-info-text-weight);\\n\\t\\tfont-size: var(--block-info-text-size);\\n\\t\\tline-height: var(--line-sm);\\n\\t}\\n\\tdiv > :global(.md.prose *) {\\n\\t\\tcolor: var(--block-info-text-color);\\n\\t}\\n\\tdiv {\\n\\t\\tmargin-bottom: var(--spacing-md);\\n\\t}</style>\\n"],"names":[],"mappings":"AASC,iBAAG,CAAW,SAAW,CACxB,WAAW,CAAE,IAAI,wBAAwB,CAAC,CAC1C,SAAS,CAAE,IAAI,sBAAsB,CAAC,CACtC,WAAW,CAAE,IAAI,SAAS,CAC3B,CACA,iBAAG,CAAW,WAAa,CAC1B,KAAK,CAAE,IAAI,uBAAuB,CACnC,CACA,iBAAI,CACH,aAAa,CAAE,IAAI,YAAY,CAChC"}'},X$1=create_ssr_component((o,t,e,n)=>{let{info:l}=t;return t.info===void 0&&e.info&&l!==void 0&&e.info(l),o.css.add(D),`<div class="svelte-j9uq24">${validate_component(An,"Markdown").$$render(o,{message:l,sanitize_html:!0},{},{})} </div>`}),N={code:`span.has-info.svelte-g2oxp3{margin-bottom:var(--spacing-xs)}span.svelte-g2oxp3:not(.has-info){margin-bottom:var(--spacing-lg)}span.svelte-g2oxp3{display:inline-block;position:relative;z-index:var(--layer-4);border:solid var(--block-title-border-width)
			var(--block-title-border-color);border-radius:var(--block-title-radius);background:var(--block-title-background-fill);padding:var(--block-title-padding);color:var(--block-title-text-color);font-weight:var(--block-title-text-weight);font-size:var(--block-title-text-size);line-height:var(--line-sm)}span[dir="rtl"].svelte-g2oxp3{display:block}.hide.svelte-g2oxp3{margin:0;height:0}`,map:'{"version":3,"file":"BlockTitle.svelte","sources":["BlockTitle.svelte"],"sourcesContent":["<script lang=\\"ts\\">import { default as Info } from \\"./Info.svelte\\";\\nexport let show_label = true;\\nexport let info = void 0;\\nexport let rtl = false;\\n<\/script>\\n\\n<span\\n\\tclass:sr-only={!show_label}\\n\\tclass:hide={!show_label}\\n\\tclass:has-info={info != null}\\n\\tdata-testid=\\"block-info\\"\\n\\tdir={rtl ? \\"rtl\\" : \\"ltr\\"}\\n>\\n\\t<slot />\\n</span>\\n{#if info}\\n\\t<Info {info} />\\n{/if}\\n\\n<style>\\n\\tspan.has-info {\\n\\t\\tmargin-bottom: var(--spacing-xs);\\n\\t}\\n\\tspan:not(.has-info) {\\n\\t\\tmargin-bottom: var(--spacing-lg);\\n\\t}\\n\\tspan {\\n\\t\\tdisplay: inline-block;\\n\\t\\tposition: relative;\\n\\t\\tz-index: var(--layer-4);\\n\\t\\tborder: solid var(--block-title-border-width)\\n\\t\\t\\tvar(--block-title-border-color);\\n\\t\\tborder-radius: var(--block-title-radius);\\n\\t\\tbackground: var(--block-title-background-fill);\\n\\t\\tpadding: var(--block-title-padding);\\n\\t\\tcolor: var(--block-title-text-color);\\n\\t\\tfont-weight: var(--block-title-text-weight);\\n\\t\\tfont-size: var(--block-title-text-size);\\n\\t\\tline-height: var(--line-sm);\\n\\t}\\n\\n\\tspan[dir=\\"rtl\\"] {\\n\\t\\tdisplay: block;\\n\\t}\\n\\n\\t.hide {\\n\\t\\tmargin: 0;\\n\\t\\theight: 0;\\n\\t}</style>\\n"],"names":[],"mappings":"AAoBC,IAAI,uBAAU,CACb,aAAa,CAAE,IAAI,YAAY,CAChC,CACA,kBAAI,KAAK,SAAS,CAAE,CACnB,aAAa,CAAE,IAAI,YAAY,CAChC,CACA,kBAAK,CACJ,OAAO,CAAE,YAAY,CACrB,QAAQ,CAAE,QAAQ,CAClB,OAAO,CAAE,IAAI,SAAS,CAAC,CACvB,MAAM,CAAE,KAAK,CAAC,IAAI,0BAA0B;AAC9C,GAAG,IAAI,0BAA0B,CAAC,CAChC,aAAa,CAAE,IAAI,oBAAoB,CAAC,CACxC,UAAU,CAAE,IAAI,6BAA6B,CAAC,CAC9C,OAAO,CAAE,IAAI,qBAAqB,CAAC,CACnC,KAAK,CAAE,IAAI,wBAAwB,CAAC,CACpC,WAAW,CAAE,IAAI,yBAAyB,CAAC,CAC3C,SAAS,CAAE,IAAI,uBAAuB,CAAC,CACvC,WAAW,CAAE,IAAI,SAAS,CAC3B,CAEA,IAAI,CAAC,GAAG,CAAC,KAAK,eAAE,CACf,OAAO,CAAE,KACV,CAEA,mBAAM,CACL,MAAM,CAAE,CAAC,CACT,MAAM,CAAE,CACT"}'},xt=create_ssr_component((o,t,e,n)=>{let{show_label:l=!0}=t,{info:A=void 0}=t,{rtl:i=!1}=t;return t.show_label===void 0&&e.show_label&&l!==void 0&&e.show_label(l),t.info===void 0&&e.info&&A!==void 0&&e.info(A),t.rtl===void 0&&e.rtl&&i!==void 0&&e.rtl(i),o.css.add(N),`<span data-testid="block-info"${add_attribute("dir",i?"rtl":"ltr",0)} class="${["svelte-g2oxp3",(l?"":"sr-only")+" "+(l?"":"hide")+" "+(A!=null?"has-info":"")].join(" ").trim()}">${n.default?n.default({}):""}</span> ${A?`${validate_component(X$1,"Info").$$render(o,{info:A},{},{})}`:""}`}),F={code:`label.svelte-1to105q.svelte-1to105q{display:inline-flex;align-items:center;z-index:var(--layer-2);box-shadow:var(--block-label-shadow);border:var(--block-label-border-width) solid
			var(--block-label-border-color);border-top:none;border-left:none;border-radius:var(--block-label-radius);background:var(--block-label-background-fill);padding:var(--block-label-padding);pointer-events:none;color:var(--block-label-text-color);font-weight:var(--block-label-text-weight);font-size:var(--block-label-text-size);line-height:var(--line-sm)}.gr-group label.svelte-1to105q.svelte-1to105q{border-top-left-radius:0}label.float.svelte-1to105q.svelte-1to105q{position:absolute;top:var(--block-label-margin);left:var(--block-label-margin)}label.svelte-1to105q.svelte-1to105q:not(.float){position:static;margin-top:var(--block-label-margin);margin-left:var(--block-label-margin)}.hide.svelte-1to105q.svelte-1to105q{height:0}span.svelte-1to105q.svelte-1to105q{opacity:0.8;margin-right:var(--size-2);width:calc(var(--block-label-text-size) - 1px);height:calc(var(--block-label-text-size) - 1px)}.hide-label.svelte-1to105q.svelte-1to105q{box-shadow:none;border-width:0;background:transparent;overflow:visible}label[dir="rtl"].svelte-1to105q.svelte-1to105q{border:var(--block-label-border-width) solid
			var(--block-label-border-color);border-top:none;border-right:none;border-bottom-left-radius:var(--block-radius);border-bottom-right-radius:var(--block-label-radius);border-top-left-radius:var(--block-label-radius)}label[dir="rtl"].svelte-1to105q span.svelte-1to105q{margin-left:var(--size-2);margin-right:0}`,map:'{"version":3,"file":"BlockLabel.svelte","sources":["BlockLabel.svelte"],"sourcesContent":["<script lang=\\"ts\\">export let label = null;\\nexport let Icon;\\nexport let show_label = true;\\nexport let disable = false;\\nexport let float = true;\\nexport let rtl = false;\\n<\/script>\\n\\n<label\\n\\tfor=\\"\\"\\n\\tclass:hide={!show_label}\\n\\tclass:sr-only={!show_label}\\n\\tclass:float\\n\\tclass:hide-label={disable}\\n\\tdata-testid=\\"block-label\\"\\n\\tdir={rtl ? \\"rtl\\" : \\"ltr\\"}\\n>\\n\\t<span>\\n\\t\\t<Icon />\\n\\t</span>\\n\\t{label}\\n</label>\\n\\n<style>\\n\\tlabel {\\n\\t\\tdisplay: inline-flex;\\n\\t\\talign-items: center;\\n\\t\\tz-index: var(--layer-2);\\n\\t\\tbox-shadow: var(--block-label-shadow);\\n\\t\\tborder: var(--block-label-border-width) solid\\n\\t\\t\\tvar(--block-label-border-color);\\n\\t\\tborder-top: none;\\n\\t\\tborder-left: none;\\n\\t\\tborder-radius: var(--block-label-radius);\\n\\t\\tbackground: var(--block-label-background-fill);\\n\\t\\tpadding: var(--block-label-padding);\\n\\t\\tpointer-events: none;\\n\\t\\tcolor: var(--block-label-text-color);\\n\\t\\tfont-weight: var(--block-label-text-weight);\\n\\t\\tfont-size: var(--block-label-text-size);\\n\\t\\tline-height: var(--line-sm);\\n\\t}\\n\\t:global(.gr-group) label {\\n\\t\\tborder-top-left-radius: 0;\\n\\t}\\n\\n\\tlabel.float {\\n\\t\\tposition: absolute;\\n\\t\\ttop: var(--block-label-margin);\\n\\t\\tleft: var(--block-label-margin);\\n\\t}\\n\\tlabel:not(.float) {\\n\\t\\tposition: static;\\n\\t\\tmargin-top: var(--block-label-margin);\\n\\t\\tmargin-left: var(--block-label-margin);\\n\\t}\\n\\n\\t.hide {\\n\\t\\theight: 0;\\n\\t}\\n\\n\\tspan {\\n\\t\\topacity: 0.8;\\n\\t\\tmargin-right: var(--size-2);\\n\\t\\twidth: calc(var(--block-label-text-size) - 1px);\\n\\t\\theight: calc(var(--block-label-text-size) - 1px);\\n\\t}\\n\\t.hide-label {\\n\\t\\tbox-shadow: none;\\n\\t\\tborder-width: 0;\\n\\t\\tbackground: transparent;\\n\\t\\toverflow: visible;\\n\\t}\\n\\n\\tlabel[dir=\\"rtl\\"] {\\n\\t\\tborder: var(--block-label-border-width) solid\\n\\t\\t\\tvar(--block-label-border-color);\\n\\t\\tborder-top: none;\\n\\t\\tborder-right: none;\\n\\t\\tborder-bottom-left-radius: var(--block-radius);\\n\\t\\tborder-bottom-right-radius: var(--block-label-radius);\\n\\t\\tborder-top-left-radius: var(--block-label-radius);\\n\\t}\\n\\n\\tlabel[dir=\\"rtl\\"] span {\\n\\t\\tmargin-left: var(--size-2);\\n\\t\\tmargin-right: 0;\\n\\t}</style>\\n"],"names":[],"mappings":"AAwBC,mCAAM,CACL,OAAO,CAAE,WAAW,CACpB,WAAW,CAAE,MAAM,CACnB,OAAO,CAAE,IAAI,SAAS,CAAC,CACvB,UAAU,CAAE,IAAI,oBAAoB,CAAC,CACrC,MAAM,CAAE,IAAI,0BAA0B,CAAC,CAAC;AAC1C,GAAG,IAAI,0BAA0B,CAAC,CAChC,UAAU,CAAE,IAAI,CAChB,WAAW,CAAE,IAAI,CACjB,aAAa,CAAE,IAAI,oBAAoB,CAAC,CACxC,UAAU,CAAE,IAAI,6BAA6B,CAAC,CAC9C,OAAO,CAAE,IAAI,qBAAqB,CAAC,CACnC,cAAc,CAAE,IAAI,CACpB,KAAK,CAAE,IAAI,wBAAwB,CAAC,CACpC,WAAW,CAAE,IAAI,yBAAyB,CAAC,CAC3C,SAAS,CAAE,IAAI,uBAAuB,CAAC,CACvC,WAAW,CAAE,IAAI,SAAS,CAC3B,CACQ,SAAU,CAAC,mCAAM,CACxB,sBAAsB,CAAE,CACzB,CAEA,KAAK,oCAAO,CACX,QAAQ,CAAE,QAAQ,CAClB,GAAG,CAAE,IAAI,oBAAoB,CAAC,CAC9B,IAAI,CAAE,IAAI,oBAAoB,CAC/B,CACA,mCAAK,KAAK,MAAM,CAAE,CACjB,QAAQ,CAAE,MAAM,CAChB,UAAU,CAAE,IAAI,oBAAoB,CAAC,CACrC,WAAW,CAAE,IAAI,oBAAoB,CACtC,CAEA,mCAAM,CACL,MAAM,CAAE,CACT,CAEA,kCAAK,CACJ,OAAO,CAAE,GAAG,CACZ,YAAY,CAAE,IAAI,QAAQ,CAAC,CAC3B,KAAK,CAAE,KAAK,IAAI,uBAAuB,CAAC,CAAC,CAAC,CAAC,GAAG,CAAC,CAC/C,MAAM,CAAE,KAAK,IAAI,uBAAuB,CAAC,CAAC,CAAC,CAAC,GAAG,CAChD,CACA,yCAAY,CACX,UAAU,CAAE,IAAI,CAChB,YAAY,CAAE,CAAC,CACf,UAAU,CAAE,WAAW,CACvB,QAAQ,CAAE,OACX,CAEA,KAAK,CAAC,GAAG,CAAC,KAAK,+BAAE,CAChB,MAAM,CAAE,IAAI,0BAA0B,CAAC,CAAC;AAC1C,GAAG,IAAI,0BAA0B,CAAC,CAChC,UAAU,CAAE,IAAI,CAChB,YAAY,CAAE,IAAI,CAClB,yBAAyB,CAAE,IAAI,cAAc,CAAC,CAC9C,0BAA0B,CAAE,IAAI,oBAAoB,CAAC,CACrD,sBAAsB,CAAE,IAAI,oBAAoB,CACjD,CAEA,KAAK,CAAC,GAAG,CAAC,KAAK,gBAAC,CAAC,mBAAK,CACrB,WAAW,CAAE,IAAI,QAAQ,CAAC,CAC1B,YAAY,CAAE,CACf"}'},bt$1=create_ssr_component((o,t,e,n)=>{let{label:l=null}=t,{Icon:A}=t,{show_label:i=!0}=t,{disable:s=!1}=t,{float:a=!0}=t,{rtl:d=!1}=t;return t.label===void 0&&e.label&&l!==void 0&&e.label(l),t.Icon===void 0&&e.Icon&&A!==void 0&&e.Icon(A),t.show_label===void 0&&e.show_label&&i!==void 0&&e.show_label(i),t.disable===void 0&&e.disable&&s!==void 0&&e.disable(s),t.float===void 0&&e.float&&a!==void 0&&e.float(a),t.rtl===void 0&&e.rtl&&d!==void 0&&e.rtl(d),o.css.add(F),`<label for="" data-testid="block-label"${add_attribute("dir",d?"rtl":"ltr",0)} class="${["svelte-1to105q",(i?"":"hide")+" "+(i?"":"sr-only")+" "+(a?"float":"")+" "+(s?"hide-label":"")].join(" ").trim()}"><span class="svelte-1to105q">${validate_component(A,"Icon").$$render(o,{},{},{})}</span> ${escape(l)} </label>`}),J={code:"button.svelte-vzs2gq{display:flex;justify-content:center;align-items:center;gap:1px;z-index:var(--layer-2);border-radius:var(--radius-xs);color:var(--block-label-text-color);border:1px solid transparent;padding:var(--spacing-xxs)}button.svelte-vzs2gq:hover{background-color:var(--background-fill-secondary)}button[disabled].svelte-vzs2gq{opacity:0.5;box-shadow:none}button[disabled].svelte-vzs2gq:hover{cursor:not-allowed}.padded.svelte-vzs2gq{background:var(--bg-color)}button.svelte-vzs2gq:hover,button.highlight.svelte-vzs2gq{cursor:pointer;color:var(--color-accent)}.padded.svelte-vzs2gq:hover{color:var(--block-label-text-color)}span.svelte-vzs2gq{padding:0px 1px;font-size:10px}div.svelte-vzs2gq{display:flex;align-items:center;justify-content:center;transition:filter 0.2s ease-in-out}.x-small.svelte-vzs2gq{width:10px;height:10px}.small.svelte-vzs2gq{width:14px;height:14px}.medium.svelte-vzs2gq{width:20px;height:20px}.large.svelte-vzs2gq{width:22px;height:22px}.pending.svelte-vzs2gq{animation:svelte-vzs2gq-flash 0.5s infinite}@keyframes svelte-vzs2gq-flash{0%{opacity:0.5}50%{opacity:1}100%{opacity:0.5}}.transparent.svelte-vzs2gq{background:transparent;border:none;box-shadow:none}",map:'{"version":3,"file":"IconButton.svelte","sources":["IconButton.svelte"],"sourcesContent":["<script lang=\\"ts\\">import {} from \\"svelte\\";\\nexport let Icon;\\nexport let label = \\"\\";\\nexport let show_label = false;\\nexport let pending = false;\\nexport let size = \\"small\\";\\nexport let padded = true;\\nexport let highlight = false;\\nexport let disabled = false;\\nexport let hasPopup = false;\\nexport let color = \\"var(--block-label-text-color)\\";\\nexport let transparent = false;\\nexport let background = \\"var(--block-background-fill)\\";\\n$: _color = highlight ? \\"var(--color-accent)\\" : color;\\n<\/script>\\n\\n<button\\n\\t{disabled}\\n\\ton:click\\n\\taria-label={label}\\n\\taria-haspopup={hasPopup}\\n\\ttitle={label}\\n\\tclass:pending\\n\\tclass:padded\\n\\tclass:highlight\\n\\tclass:transparent\\n\\tstyle:color={!disabled && _color ? _color : \\"var(--block-label-text-color)\\"}\\n\\tstyle:--bg-color={!disabled ? background : \\"auto\\"}\\n>\\n\\t{#if show_label}<span>{label}</span>{/if}\\n\\t<div\\n\\t\\tclass:x-small={size === \\"x-small\\"}\\n\\t\\tclass:small={size === \\"small\\"}\\n\\t\\tclass:large={size === \\"large\\"}\\n\\t\\tclass:medium={size === \\"medium\\"}\\n\\t>\\n\\t\\t<svelte:component this={Icon} />\\n\\t\\t<slot />\\n\\t</div>\\n</button>\\n\\n<style>\\n\\tbutton {\\n\\t\\tdisplay: flex;\\n\\t\\tjustify-content: center;\\n\\t\\talign-items: center;\\n\\t\\tgap: 1px;\\n\\t\\tz-index: var(--layer-2);\\n\\t\\tborder-radius: var(--radius-xs);\\n\\t\\tcolor: var(--block-label-text-color);\\n\\t\\tborder: 1px solid transparent;\\n\\t\\tpadding: var(--spacing-xxs);\\n\\t}\\n\\n\\tbutton:hover {\\n\\t\\tbackground-color: var(--background-fill-secondary);\\n\\t}\\n\\n\\tbutton[disabled] {\\n\\t\\topacity: 0.5;\\n\\t\\tbox-shadow: none;\\n\\t}\\n\\n\\tbutton[disabled]:hover {\\n\\t\\tcursor: not-allowed;\\n\\t}\\n\\n\\t.padded {\\n\\t\\tbackground: var(--bg-color);\\n\\t}\\n\\n\\tbutton:hover,\\n\\tbutton.highlight {\\n\\t\\tcursor: pointer;\\n\\t\\tcolor: var(--color-accent);\\n\\t}\\n\\n\\t.padded:hover {\\n\\t\\tcolor: var(--block-label-text-color);\\n\\t}\\n\\n\\tspan {\\n\\t\\tpadding: 0px 1px;\\n\\t\\tfont-size: 10px;\\n\\t}\\n\\n\\tdiv {\\n\\t\\tdisplay: flex;\\n\\t\\talign-items: center;\\n\\t\\tjustify-content: center;\\n\\t\\ttransition: filter 0.2s ease-in-out;\\n\\t}\\n\\n\\t.x-small {\\n\\t\\twidth: 10px;\\n\\t\\theight: 10px;\\n\\t}\\n\\n\\t.small {\\n\\t\\twidth: 14px;\\n\\t\\theight: 14px;\\n\\t}\\n\\n\\t.medium {\\n\\t\\twidth: 20px;\\n\\t\\theight: 20px;\\n\\t}\\n\\n\\t.large {\\n\\t\\twidth: 22px;\\n\\t\\theight: 22px;\\n\\t}\\n\\n\\t.pending {\\n\\t\\tanimation: flash 0.5s infinite;\\n\\t}\\n\\n\\t@keyframes flash {\\n\\t\\t0% {\\n\\t\\t\\topacity: 0.5;\\n\\t\\t}\\n\\t\\t50% {\\n\\t\\t\\topacity: 1;\\n\\t\\t}\\n\\t\\t100% {\\n\\t\\t\\topacity: 0.5;\\n\\t\\t}\\n\\t}\\n\\n\\t.transparent {\\n\\t\\tbackground: transparent;\\n\\t\\tborder: none;\\n\\t\\tbox-shadow: none;\\n\\t}</style>\\n"],"names":[],"mappings":"AA0CC,oBAAO,CACN,OAAO,CAAE,IAAI,CACb,eAAe,CAAE,MAAM,CACvB,WAAW,CAAE,MAAM,CACnB,GAAG,CAAE,GAAG,CACR,OAAO,CAAE,IAAI,SAAS,CAAC,CACvB,aAAa,CAAE,IAAI,WAAW,CAAC,CAC/B,KAAK,CAAE,IAAI,wBAAwB,CAAC,CACpC,MAAM,CAAE,GAAG,CAAC,KAAK,CAAC,WAAW,CAC7B,OAAO,CAAE,IAAI,aAAa,CAC3B,CAEA,oBAAM,MAAO,CACZ,gBAAgB,CAAE,IAAI,2BAA2B,CAClD,CAEA,MAAM,CAAC,QAAQ,eAAE,CAChB,OAAO,CAAE,GAAG,CACZ,UAAU,CAAE,IACb,CAEA,MAAM,CAAC,QAAQ,eAAC,MAAO,CACtB,MAAM,CAAE,WACT,CAEA,qBAAQ,CACP,UAAU,CAAE,IAAI,UAAU,CAC3B,CAEA,oBAAM,MAAM,CACZ,MAAM,wBAAW,CAChB,MAAM,CAAE,OAAO,CACf,KAAK,CAAE,IAAI,cAAc,CAC1B,CAEA,qBAAO,MAAO,CACb,KAAK,CAAE,IAAI,wBAAwB,CACpC,CAEA,kBAAK,CACJ,OAAO,CAAE,GAAG,CAAC,GAAG,CAChB,SAAS,CAAE,IACZ,CAEA,iBAAI,CACH,OAAO,CAAE,IAAI,CACb,WAAW,CAAE,MAAM,CACnB,eAAe,CAAE,MAAM,CACvB,UAAU,CAAE,MAAM,CAAC,IAAI,CAAC,WACzB,CAEA,sBAAS,CACR,KAAK,CAAE,IAAI,CACX,MAAM,CAAE,IACT,CAEA,oBAAO,CACN,KAAK,CAAE,IAAI,CACX,MAAM,CAAE,IACT,CAEA,qBAAQ,CACP,KAAK,CAAE,IAAI,CACX,MAAM,CAAE,IACT,CAEA,oBAAO,CACN,KAAK,CAAE,IAAI,CACX,MAAM,CAAE,IACT,CAEA,sBAAS,CACR,SAAS,CAAE,mBAAK,CAAC,IAAI,CAAC,QACvB,CAEA,WAAW,mBAAM,CAChB,EAAG,CACF,OAAO,CAAE,GACV,CACA,GAAI,CACH,OAAO,CAAE,CACV,CACA,IAAK,CACJ,OAAO,CAAE,GACV,CACD,CAEA,0BAAa,CACZ,UAAU,CAAE,WAAW,CACvB,MAAM,CAAE,IAAI,CACZ,UAAU,CAAE,IACb"}'},j=create_ssr_component((o,t,e,n)=>{let l,{Icon:A}=t,{label:i=""}=t,{show_label:s=!1}=t,{pending:a=!1}=t,{size:d="small"}=t,{padded:g=!0}=t,{highlight:h=!1}=t,{disabled:p=!1}=t,{hasPopup:m=!1}=t,{color:x="var(--block-label-text-color)"}=t,{transparent:b=!1}=t,{background:k="var(--block-background-fill)"}=t;return t.Icon===void 0&&e.Icon&&A!==void 0&&e.Icon(A),t.label===void 0&&e.label&&i!==void 0&&e.label(i),t.show_label===void 0&&e.show_label&&s!==void 0&&e.show_label(s),t.pending===void 0&&e.pending&&a!==void 0&&e.pending(a),t.size===void 0&&e.size&&d!==void 0&&e.size(d),t.padded===void 0&&e.padded&&g!==void 0&&e.padded(g),t.highlight===void 0&&e.highlight&&h!==void 0&&e.highlight(h),t.disabled===void 0&&e.disabled&&p!==void 0&&e.disabled(p),t.hasPopup===void 0&&e.hasPopup&&m!==void 0&&e.hasPopup(m),t.color===void 0&&e.color&&x!==void 0&&e.color(x),t.transparent===void 0&&e.transparent&&b!==void 0&&e.transparent(b),t.background===void 0&&e.background&&k!==void 0&&e.background(k),o.css.add(J),l=h?"var(--color-accent)":x,`<button ${p?"disabled":""}${add_attribute("aria-label",i,0)}${add_attribute("aria-haspopup",m,0)}${add_attribute("title",i,0)} class="${["svelte-vzs2gq",(a?"pending":"")+" "+(g?"padded":"")+" "+(h?"highlight":"")+" "+(b?"transparent":"")].join(" ").trim()}"${add_styles({color:!p&&l?l:"var(--block-label-text-color)","--bg-color":p?"auto":k})}>${s?`<span class="svelte-vzs2gq">${escape(i)}</span>`:""} <div class="${["svelte-vzs2gq",(d==="x-small"?"x-small":"")+" "+(d==="small"?"small":"")+" "+(d==="large"?"large":"")+" "+(d==="medium"?"medium":"")].join(" ").trim()}">${validate_component(A||missing_component,"svelte:component").$$render(o,{},{},{})} ${n.default?n.default({}):""}</div> </button>`}),tt={code:".empty.svelte-1oiin9d{display:flex;justify-content:center;align-items:center;margin-top:calc(0px - var(--size-6));height:var(--size-full)}.icon.svelte-1oiin9d{opacity:0.5;height:var(--size-5);color:var(--body-text-color)}.small.svelte-1oiin9d{min-height:calc(var(--size-32) - 20px)}.large.svelte-1oiin9d{min-height:calc(var(--size-64) - 20px)}.unpadded_box.svelte-1oiin9d{margin-top:0}.small_parent.svelte-1oiin9d{min-height:100% !important}",map:'{"version":3,"file":"Empty.svelte","sources":["Empty.svelte"],"sourcesContent":["<script lang=\\"ts\\">export let size = \\"small\\";\\nexport let unpadded_box = false;\\nlet el;\\n$: parent_height = compare_el_to_parent(el);\\nfunction compare_el_to_parent(el2) {\\n    if (!el2)\\n        return false;\\n    const { height: el_height } = el2.getBoundingClientRect();\\n    const { height: parent_height2 } = el2.parentElement?.getBoundingClientRect() || { height: el_height };\\n    return el_height > parent_height2 + 2;\\n}\\n<\/script>\\n\\n<div\\n\\tclass=\\"empty\\"\\n\\tclass:small={size === \\"small\\"}\\n\\tclass:large={size === \\"large\\"}\\n\\tclass:unpadded_box\\n\\tbind:this={el}\\n\\tclass:small_parent={parent_height}\\n\\taria-label=\\"Empty value\\"\\n>\\n\\t<div class=\\"icon\\">\\n\\t\\t<slot />\\n\\t</div>\\n</div>\\n\\n<style>\\n\\t.empty {\\n\\t\\tdisplay: flex;\\n\\t\\tjustify-content: center;\\n\\t\\talign-items: center;\\n\\t\\tmargin-top: calc(0px - var(--size-6));\\n\\t\\theight: var(--size-full);\\n\\t}\\n\\n\\t.icon {\\n\\t\\topacity: 0.5;\\n\\t\\theight: var(--size-5);\\n\\t\\tcolor: var(--body-text-color);\\n\\t}\\n\\n\\t.small {\\n\\t\\tmin-height: calc(var(--size-32) - 20px);\\n\\t}\\n\\n\\t.large {\\n\\t\\tmin-height: calc(var(--size-64) - 20px);\\n\\t}\\n\\n\\t.unpadded_box {\\n\\t\\tmargin-top: 0;\\n\\t}\\n\\n\\t.small_parent {\\n\\t\\tmin-height: 100% !important;\\n\\t}</style>\\n"],"names":[],"mappings":"AA4BC,qBAAO,CACN,OAAO,CAAE,IAAI,CACb,eAAe,CAAE,MAAM,CACvB,WAAW,CAAE,MAAM,CACnB,UAAU,CAAE,KAAK,GAAG,CAAC,CAAC,CAAC,IAAI,QAAQ,CAAC,CAAC,CACrC,MAAM,CAAE,IAAI,WAAW,CACxB,CAEA,oBAAM,CACL,OAAO,CAAE,GAAG,CACZ,MAAM,CAAE,IAAI,QAAQ,CAAC,CACrB,KAAK,CAAE,IAAI,iBAAiB,CAC7B,CAEA,qBAAO,CACN,UAAU,CAAE,KAAK,IAAI,SAAS,CAAC,CAAC,CAAC,CAAC,IAAI,CACvC,CAEA,qBAAO,CACN,UAAU,CAAE,KAAK,IAAI,SAAS,CAAC,CAAC,CAAC,CAAC,IAAI,CACvC,CAEA,4BAAc,CACb,UAAU,CAAE,CACb,CAEA,4BAAc,CACb,UAAU,CAAE,IAAI,CAAC,UAClB"}'};function et$1(o){return !1}const kt=create_ssr_component((o,t,e,n)=>{let l,{size:A="small"}=t,{unpadded_box:i=!1}=t,s;return t.size===void 0&&e.size&&A!==void 0&&e.size(A),t.unpadded_box===void 0&&e.unpadded_box&&i!==void 0&&e.unpadded_box(i),o.css.add(tt),l=et$1(),`<div class="${["empty svelte-1oiin9d",(A==="small"?"small":"")+" "+(A==="large"?"large":"")+" "+(i?"unpadded_box":"")+" "+(l?"small_parent":"")].join(" ").trim()}" aria-label="Empty value"${add_attribute("this",s,0)}><div class="icon svelte-1oiin9d">${n.default?n.default({}):""}</div> </div>`});const yt$1=create_ssr_component((o,t,e,n)=>'<svg xmlns="http://www.w3.org/2000/svg" width="24px" height="24px" fill="currentColor" stroke-width="1.5" viewBox="0 0 24 24" color="currentColor"><path stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" d="M21.044 5.704a.6.6 0 0 1 .956.483v11.626a.6.6 0 0 1-.956.483l-7.889-5.813a.6.6 0 0 1 0-.966l7.89-5.813ZM10.044 5.704a.6.6 0 0 1 .956.483v11.626a.6.6 0 0 1-.956.483l-7.888-5.813a.6.6 0 0 1 0-.966l7.888-5.813Z"></path></svg>'),_t=create_ssr_component((o,t,e,n)=>'<svg xmlns="http://www.w3.org/2000/svg" width="24px" height="24px" viewBox="0 0 24 24"><rect x="2" y="4" width="20" height="18" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" fill="none"></rect><line x1="2" y1="9" x2="22" y2="9" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" fill="none"></line><line x1="7" y1="2" x2="7" y2="6" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" fill="none"></line><line x1="17" y1="2" x2="17" y2="6" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" fill="none"></line></svg>'),zt=create_ssr_component((o,t,e,n)=>'<svg xmlns="http://www.w3.org/2000/svg" width="100%" height="100%" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" class="feather feather-camera"><path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"></path><circle cx="12" cy="13" r="4"></circle></svg>');const Kt=create_ssr_component((o,t,e,n)=>'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" aria-hidden="true" role="img" class="iconify iconify--carbon" width="100%" height="100%" preserveAspectRatio="xMidYMid meet" viewBox="0 0 32 32"><path fill="currentColor" d="M17.74 30L16 29l4-7h6a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h9v2H6a4 4 0 0 1-4-4V8a4 4 0 0 1 4-4h20a4 4 0 0 1 4 4v12a4 4 0 0 1-4 4h-4.84Z"></path><path fill="currentColor" d="M8 10h16v2H8zm0 6h10v2H8z"></path></svg>'),Lt=create_ssr_component((o,t,e,n)=>'<svg width="100%" height="100%" stroke-width="1.5" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" color="currentColor"><path d="M5 13L9 17L19 7" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"></path></svg>'),Wt=create_ssr_component((o,t,e,n)=>'<svg xmlns="http://www.w3.org/2000/svg" width="100%" height="100%" viewBox="0 0 24 24" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" class="feather feather-circle"><circle cx="12" cy="12" r="10"></circle></svg>'),qt=create_ssr_component((o,t,e,n)=>'<svg width="100%" height="100%" viewBox="0 0 24 24" version="1.1" xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" xml:space="preserve" stroke="currentColor" style="fill-rule:evenodd;clip-rule:evenodd;stroke-linecap:round;stroke-linejoin:round;"><g transform="matrix(1.14096,-0.140958,-0.140958,1.14096,-0.0559523,0.0559523)"><path d="M18,6L6.087,17.913" style="fill:none;fill-rule:nonzero;stroke-width:2px;"></path></g><path d="M4.364,4.364L19.636,19.636" style="fill:none;fill-rule:nonzero;stroke-width:2px;"></path></svg>'),jt=create_ssr_component((o,t,e,n)=>'<svg width="100%" height="100%" viewBox="0 0 32 32"><path fill="currentColor" d="m31 16l-7 7l-1.41-1.41L28.17 16l-5.58-5.59L24 9l7 7zM1 16l7-7l1.41 1.41L3.83 16l5.58 5.59L8 23l-7-7zm11.42 9.484L17.64 6l1.932.517L14.352 26z"></path></svg>');const ot$1=create_ssr_component((o,t,e,n)=>'<svg id="icon" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32" width="100%" height="100%"><path d="M23,20a5,5,0,0,0-3.89,1.89L11.8,17.32a4.46,4.46,0,0,0,0-2.64l7.31-4.57A5,5,0,1,0,18,7a4.79,4.79,0,0,0,.2,1.32l-7.31,4.57a5,5,0,1,0,0,6.22l7.31,4.57A4.79,4.79,0,0,0,18,25a5,5,0,1,0,5-5ZM23,4a3,3,0,1,1-3,3A3,3,0,0,1,23,4ZM7,19a3,3,0,1,1,3-3A3,3,0,0,1,7,19Zm16,9a3,3,0,1,1,3-3A3,3,0,0,1,23,28Z" fill="currentColor"></path></svg>'),Zt=create_ssr_component((o,t,e,n)=>'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 33 33" color="currentColor" aria-hidden="true" width="100%" height="100%"><path fill="currentColor" d="M28 10v18H10V10h18m0-2H10a2 2 0 0 0-2 2v18a2 2 0 0 0 2 2h18a2 2 0 0 0 2-2V10a2 2 0 0 0-2-2Z"></path><path fill="currentColor" d="M4 18H2V4a2 2 0 0 1 2-2h14v2H4Z"></path></svg>'),Ut=create_ssr_component((o,t,e,n)=>'<svg xmlns="http://www.w3.org/2000/svg" width="100%" height="100%" viewBox="0 0 32 32"><path fill="currentColor" d="M26 24v4H6v-4H4v4a2 2 0 0 0 2 2h20a2 2 0 0 0 2-2v-4zm0-10l-1.41-1.41L17 20.17V2h-2v18.17l-7.59-7.58L6 14l10 10l10-10z"></path></svg>'),nt$1={code:".dropdown-arrow.svelte-xjn76a{fill:currentColor}",map:'{"version":3,"file":"DropdownArrow.svelte","sources":["DropdownArrow.svelte"],"sourcesContent":["<svg\\n\\tclass=\\"dropdown-arrow\\"\\n\\txmlns=\\"http://www.w3.org/2000/svg\\"\\n\\twidth=\\"100%\\"\\n\\theight=\\"100%\\"\\n\\tviewBox=\\"0 0 18 18\\"\\n>\\n\\t<path d=\\"M5 8l4 4 4-4z\\" />\\n</svg>\\n\\n<style>\\n\\t.dropdown-arrow {\\n\\t\\tfill: currentColor;\\n\\t\\t/* margin-right: var(--size-2); */\\n\\t\\t/* width: var(--size-5); */\\n\\t}</style>\\n"],"names":[],"mappings":"AAWC,6BAAgB,CACf,IAAI,CAAE,YAGP"}'},Vt=create_ssr_component((o,t,e,n)=>(o.css.add(nt$1),'<svg class="dropdown-arrow svelte-xjn76a" xmlns="http://www.w3.org/2000/svg" width="100%" height="100%" viewBox="0 0 18 18"><path d="M5 8l4 4 4-4z"></path></svg>')),rt$1={code:".dropdown-arrow.svelte-1m886t3{fill:currentColor}.circle.svelte-1m886t3{fill:currentColor;opacity:0.1}",map:'{"version":3,"file":"DropdownCircularArrow.svelte","sources":["DropdownCircularArrow.svelte"],"sourcesContent":["<svg\\n\\tclass=\\"dropdown-arrow\\"\\n\\txmlns=\\"http://www.w3.org/2000/svg\\"\\n\\twidth=\\"100%\\"\\n\\theight=\\"100%\\"\\n\\tviewBox=\\"0 0 18 18\\"\\n>\\n\\t<circle cx=\\"9\\" cy=\\"9\\" r=\\"8\\" class=\\"circle\\" />\\n\\t<path d=\\"M5 8l4 4 4-4z\\" />\\n</svg>\\n\\n<style>\\n\\t.dropdown-arrow {\\n\\t\\tfill: currentColor;\\n\\t}\\n\\n\\t.circle {\\n\\t\\tfill: currentColor;\\n\\t\\topacity: 0.1;\\n\\t}</style>\\n"],"names":[],"mappings":"AAYC,8BAAgB,CACf,IAAI,CAAE,YACP,CAEA,sBAAQ,CACP,IAAI,CAAE,YAAY,CAClB,OAAO,CAAE,GACV"}'},Tt=create_ssr_component((o,t,e,n)=>(o.css.add(rt$1),'<svg class="dropdown-arrow svelte-1m886t3" xmlns="http://www.w3.org/2000/svg" width="100%" height="100%" viewBox="0 0 18 18"><circle cx="9" cy="9" r="8" class="circle svelte-1m886t3"></circle><path d="M5 8l4 4 4-4z"></path></svg>')),St=create_ssr_component((o,t,e,n)=>'<svg xmlns="http://www.w3.org/2000/svg" width="100%" height="100%" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" class="feather feather-edit-2"><path d="M17 3a2.828 2.828 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5L17 3z"></path></svg>'),Yt=create_ssr_component((o,t,e,n)=>'<svg fill="none" stroke="currentColor" viewBox="0 0 24 24" width="100%" height="100%" xmlns="http://www.w3.org/2000/svg" aria-hidden="true" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path stroke-linecap="round" stroke-linejoin="round" d="M12 9v3.75m9-.75a9 9 0 11-18 0 9 9 0 0118 0zm-9 3.75h.008v.008H12v-.008z"></path></svg>'),Qt=create_ssr_component((o,t,e,n)=>'<svg xmlns="http://www.w3.org/2000/svg" width="24px" height="24px" fill="currentColor" stroke-width="1.5" viewBox="0 0 24 24" color="currentColor"><path stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" d="M2.956 5.704A.6.6 0 0 0 2 6.187v11.626a.6.6 0 0 0 .956.483l7.889-5.813a.6.6 0 0 0 0-.966l-7.89-5.813ZM13.956 5.704a.6.6 0 0 0-.956.483v11.626a.6.6 0 0 0 .956.483l7.889-5.813a.6.6 0 0 0 0-.966l-7.89-5.813Z"></path></svg>'),Rt=create_ssr_component((o,t,e,n)=>'<svg xmlns="http://www.w3.org/2000/svg" width="100%" height="100%" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" class="feather feather-file"><path d="M13 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"></path><polyline points="13 2 13 9 20 9"></polyline></svg>'),Pt=create_ssr_component((o,t,e,n)=>'<svg fill="none" stroke="currentColor" viewBox="0 0 24 24" width="100%" height="100%" xmlns="http://www.w3.org/2000/svg" aria-hidden="true" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path stroke-linecap="round" stroke-linejoin="round" d="M11.25 11.25l.041-.02a.75.75 0 011.063.852l-.708 2.836a.75.75 0 001.063.853l.041-.021M21 12a9 9 0 11-18 0 9 9 0 0118 0zm-9-3.75h.008v.008H12V8.25z"></path></svg>'),Dt=create_ssr_component((o,t,e,n)=>'<svg fill="none" stroke="currentColor" viewBox="0 0 24 24" width="100%" height="100%" xmlns="http://www.w3.org/2000/svg" aria-hidden="true" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path stroke-linecap="round" stroke-linejoin="round" d="M9 12.75L11.25 15 15 9.75M21 12a9 9 0 11-18 0 9 9 0 0118 0z"></path></svg>'),Xt$1=create_ssr_component((o,t,e,n)=>'<svg xmlns="http://www.w3.org/2000/svg" width="100%" height="100%" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" class="feather feather-image"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"></rect><circle cx="8.5" cy="8.5" r="1.5"></circle><polyline points="21 15 16 10 5 21"></polyline></svg>'),H=create_ssr_component((o,t,e,n)=>'<svg xmlns="http://www.w3.org/2000/svg" width="100%" height="100%" viewBox="0 0 256 256"><path fill="currentColor" d="M200 32h-36.26a47.92 47.92 0 0 0-71.48 0H56a16 16 0 0 0-16 16v168a16 16 0 0 0 16 16h144a16 16 0 0 0 16-16V48a16 16 0 0 0-16-16m-72 0a32 32 0 0 1 32 32H96a32 32 0 0 1 32-32m72 184H56V48h26.75A47.9 47.9 0 0 0 80 64v8a8 8 0 0 0 8 8h80a8 8 0 0 0 8-8v-8a47.9 47.9 0 0 0-2.75-16H200Z"></path></svg>'),Nt=create_ssr_component((o,t,e,n)=>'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" aria-hidden="true" role="img" class="iconify iconify--mdi" width="100%" height="100%" preserveAspectRatio="xMidYMid meet" viewBox="0 0 24 24"><path fill="currentColor" d="M5 3h2v2H5v5a2 2 0 0 1-2 2a2 2 0 0 1 2 2v5h2v2H5c-1.07-.27-2-.9-2-2v-4a2 2 0 0 0-2-2H0v-2h1a2 2 0 0 0 2-2V5a2 2 0 0 1 2-2m14 0a2 2 0 0 1 2 2v4a2 2 0 0 0 2 2h1v2h-1a2 2 0 0 0-2 2v4a2 2 0 0 1-2 2h-2v-2h2v-5a2 2 0 0 1 2-2a2 2 0 0 1-2-2V5h-2V3h2m-7 12a1 1 0 0 1 1 1a1 1 0 0 1-1 1a1 1 0 0 1-1-1a1 1 0 0 1 1-1m-4 0a1 1 0 0 1 1 1a1 1 0 0 1-1 1a1 1 0 0 1-1-1a1 1 0 0 1 1-1m8 0a1 1 0 0 1 1 1a1 1 0 0 1-1 1a1 1 0 0 1-1-1a1 1 0 0 1 1-1Z"></path></svg>'),Jt=create_ssr_component((o,t,e,n)=>'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" aria-hidden="true" role="img" class="iconify iconify--carbon" width="100%" height="100%" preserveAspectRatio="xMidYMid meet" viewBox="0 0 32 32"><path fill="currentColor" d="M4 2H2v26a2 2 0 0 0 2 2h26v-2H4v-3h22v-8H4v-4h14V5H4Zm20 17v4H4v-4ZM16 7v4H4V7Z"></path></svg>'),lt$2=create_ssr_component((o,t,e,n)=>'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="feather feather-maximize" width="100%" height="100%"><path d="M8 3H5a2 2 0 0 0-2 2v3m18 0V5a2 2 0 0 0-2-2h-3m0 18h3a2 2 0 0 0 2-2v-3M3 16v3a2 2 0 0 0 2 2h3"></path></svg>'),At=create_ssr_component((o,t,e,n)=>'<svg xmlns="http://www.w3.org/2000/svg" width="100%" height="100%" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="feather feather-mic"><path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"></path><path d="M19 10v2a7 7 0 0 1-14 0v-2"></path><line x1="12" y1="19" x2="12" y2="23"></line><line x1="8" y1="23" x2="16" y2="23"></line></svg>'),it$2=create_ssr_component((o,t,e,n)=>'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="feather feather-minimize" width="100%" height="100%"><path d="M8 3v3a2 2 0 0 1-2 2H3m18 0h-3a2 2 0 0 1-2-2V3m0 18v-3a2 2 0 0 1 2-2h3M3 16h3a2 2 0 0 1 2 2v3"></path></svg>'),te=create_ssr_component((o,t,e,n)=>'<svg xmlns="http://www.w3.org/2000/svg" width="100%" height="100%" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" class="feather feather-music"><path d="M9 18V5l12-2v13"></path><circle cx="6" cy="18" r="3"></circle><circle cx="18" cy="16" r="3"></circle></svg>');const oe=create_ssr_component((o,t,e,n)=>'<svg fill="currentColor" width="100%" height="100%" viewBox="0 0 1920 1920" xmlns="http://www.w3.org/2000/svg"><g id="SVGRepo_bgCarrier" stroke-width="0"></g><g id="SVGRepo_tracerCarrier" stroke-linecap="round" stroke-linejoin="round"></g><g id="SVGRepo_iconCarrier"><path d="M1752.768 221.109C1532.646.986 1174.283.986 954.161 221.109l-838.588 838.588c-154.052 154.165-154.052 404.894 0 558.946 149.534 149.421 409.976 149.308 559.059 0l758.738-758.626c87.982-88.094 87.982-231.417 0-319.51-88.32-88.208-231.642-87.982-319.51 0l-638.796 638.908 79.85 79.849 638.795-638.908c43.934-43.821 115.539-43.934 159.812 0 43.934 44.047 43.934 115.877 0 159.812l-758.739 758.625c-110.23 110.118-289.355 110.005-399.36 0-110.118-110.117-110.005-289.242 0-399.247l838.588-838.588c175.963-175.962 462.382-176.188 638.909 0 176.075 176.188 176.075 462.833 0 638.908l-798.607 798.72 79.849 79.85 798.607-798.72c220.01-220.123 220.01-578.485 0-798.607" fill-rule="evenodd"></path></g></svg>'),ne=create_ssr_component((o,t,e,n)=>'<svg xmlns="http://www.w3.org/2000/svg" width="100%" height="100%" viewBox="0 0 24 24" fill="currentColor" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><rect x="6" y="4" width="4" height="16"></rect><rect x="14" y="4" width="4" height="16"></rect></svg>'),re=create_ssr_component((o,t,e,n)=>'<svg xmlns="http://www.w3.org/2000/svg" width="100%" height="100%" viewBox="0 0 24 24" fill="currentColor" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><polygon points="5 3 19 12 5 21 5 3"></polygon></svg>'),le=create_ssr_component((o,t,e,n)=>'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" aria-hidden="true" role="img" class="iconify iconify--carbon" width="100%" height="100%" preserveAspectRatio="xMidYMid meet" viewBox="0 0 32 32"><circle cx="20" cy="4" r="2" fill="currentColor"></circle><circle cx="8" cy="16" r="2" fill="currentColor"></circle><circle cx="28" cy="12" r="2" fill="currentColor"></circle><circle cx="11" cy="7" r="2" fill="currentColor"></circle><circle cx="16" cy="24" r="2" fill="currentColor"></circle><path fill="currentColor" d="M30 3.413L28.586 2L4 26.585V2H2v26a2 2 0 0 0 2 2h26v-2H5.413Z"></path></svg>'),Ae=create_ssr_component((o,t,e,n)=>'<svg width="100%" height="100%" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg"><path d="M6 12H12M18 12H12M12 12V6M12 12V18" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"></path></svg>'),se=create_ssr_component((o,t,e,n)=>'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="100%" height="100%"><path d="M19 6.41L17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z"></path></svg>');const ae=create_ssr_component((o,t,e,n)=>'<svg viewBox="0 0 22 24" width="100%" height="100%" fill="none" xmlns="http://www.w3.org/2000/svg"><g id="SVGRepo_bgCarrier" stroke-width="0"></g><g id="SVGRepo_tracerCarrier" stroke-linecap="round" stroke-linejoin="round"></g><g id="SVGRepo_iconCarrier"><path d="M19.1168 12.1484C19.474 12.3581 19.9336 12.2384 20.1432 11.8811C20.3528 11.5238 20.2331 11.0643 19.8758 10.8547L19.1168 12.1484ZM6.94331 4.13656L6.55624 4.77902L6.56378 4.78344L6.94331 4.13656ZM5.92408 4.1598L5.50816 3.5357L5.50816 3.5357L5.92408 4.1598ZM5.51031 5.09156L4.76841 5.20151C4.77575 5.25101 4.78802 5.29965 4.80505 5.34671L5.51031 5.09156ZM7.12405 11.7567C7.26496 12.1462 7.69495 12.3477 8.08446 12.2068C8.47397 12.0659 8.67549 11.6359 8.53458 11.2464L7.12405 11.7567ZM19.8758 12.1484C20.2331 11.9388 20.3528 11.4793 20.1432 11.122C19.9336 10.7648 19.474 10.6451 19.1168 10.8547L19.8758 12.1484ZM6.94331 18.8666L6.56375 18.2196L6.55627 18.2241L6.94331 18.8666ZM5.92408 18.8433L5.50815 19.4674H5.50815L5.92408 18.8433ZM5.51031 17.9116L4.80505 17.6564C4.78802 17.7035 4.77575 17.7521 4.76841 17.8016L5.51031 17.9116ZM8.53458 11.7567C8.67549 11.3672 8.47397 10.9372 8.08446 10.7963C7.69495 10.6554 7.26496 10.8569 7.12405 11.2464L8.53458 11.7567ZM19.4963 12.2516C19.9105 12.2516 20.2463 11.9158 20.2463 11.5016C20.2463 11.0873 19.9105 10.7516 19.4963 10.7516V12.2516ZM7.82931 10.7516C7.4151 10.7516 7.07931 11.0873 7.07931 11.5016C7.07931 11.9158 7.4151 12.2516 7.82931 12.2516V10.7516ZM19.8758 10.8547L7.32284 3.48968L6.56378 4.78344L19.1168 12.1484L19.8758 10.8547ZM7.33035 3.49414C6.76609 3.15419 6.05633 3.17038 5.50816 3.5357L6.34 4.78391C6.40506 4.74055 6.4893 4.73863 6.55627 4.77898L7.33035 3.49414ZM5.50816 3.5357C4.95998 3.90102 4.67184 4.54987 4.76841 5.20151L6.25221 4.98161C6.24075 4.90427 6.27494 4.82727 6.34 4.78391L5.50816 3.5357ZM4.80505 5.34671L7.12405 11.7567L8.53458 11.2464L6.21558 4.83641L4.80505 5.34671ZM19.1168 10.8547L6.56378 18.2197L7.32284 19.5134L19.8758 12.1484L19.1168 10.8547ZM6.55627 18.2241C6.4893 18.2645 6.40506 18.2626 6.34 18.2192L5.50815 19.4674C6.05633 19.8327 6.76609 19.8489 7.33035 19.509L6.55627 18.2241ZM6.34 18.2192C6.27494 18.1759 6.24075 18.0988 6.25221 18.0215L4.76841 17.8016C4.67184 18.4532 4.95998 19.1021 5.50815 19.4674L6.34 18.2192ZM6.21558 18.1667L8.53458 11.7567L7.12405 11.2464L4.80505 17.6564L6.21558 18.1667ZM19.4963 10.7516H7.82931V12.2516H19.4963V10.7516Z" fill="currentColor"></path></g></svg>');const de=create_ssr_component((o,t,e,n)=>{let{fill:l="currentColor"}=t,{stroke_width:A=1.5}=t;return t.fill===void 0&&e.fill&&l!==void 0&&e.fill(l),t.stroke_width===void 0&&e.stroke_width&&A!==void 0&&e.stroke_width(A),`<svg xmlns="http://www.w3.org/2000/svg" width="100%" height="100%" viewBox="0 0 24 24"${add_attribute("fill",l,0)} stroke="currentColor"${add_attribute("stroke-width",`${A}`,0)} stroke-linecap="round" stroke-linejoin="round" class="feather feather-square"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"></rect></svg>`});const ce=create_ssr_component((o,t,e,n)=>'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" aria-hidden="true" role="img" class="iconify iconify--carbon" width="100%" height="100%" preserveAspectRatio="xMidYMid meet" viewBox="0 0 32 32"><path fill="currentColor" d="M12 15H5a3 3 0 0 1-3-3v-2a3 3 0 0 1 3-3h5V5a1 1 0 0 0-1-1H3V2h6a3 3 0 0 1 3 3zM5 9a1 1 0 0 0-1 1v2a1 1 0 0 0 1 1h5V9zm15 14v2a1 1 0 0 0 1 1h5v-4h-5a1 1 0 0 0-1 1z"></path><path fill="currentColor" d="M2 30h28V2Zm26-2h-7a3 3 0 0 1-3-3v-2a3 3 0 0 1 3-3h5v-2a1 1 0 0 0-1-1h-6v-2h6a3 3 0 0 1 3 3Z"></path></svg>'),Ce=create_ssr_component((o,t,e,n)=>`<svg id="icon" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32" fill="currentColor" width="100%" height="100%"><defs><style>.cls-1 {
				fill: none;
			}</style></defs><rect x="12" y="12" width="2" height="12"></rect><rect x="18" y="12" width="2" height="12"></rect><path d="M4,6V8H6V28a2,2,0,0,0,2,2H24a2,2,0,0,0,2-2V8h2V6ZM8,28V8H24V28Z"></path><rect x="12" y="2" width="8" height="2"></rect><rect id="_Transparent_Rectangle_" data-name="<Transparent Rectangle>" class="cls-1" width="32" height="32"></rect></svg>`);const he=create_ssr_component((o,t,e,n)=>'<svg xmlns="http://www.w3.org/2000/svg" width="100%" height="100%" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="feather feather-scissors"><circle cx="6" cy="6" r="3"></circle><circle cx="6" cy="18" r="3"></circle><line x1="20" y1="4" x2="8.12" y2="15.88"></line><line x1="14.47" y1="14.48" x2="20" y2="20"></line><line x1="8.12" y1="8.12" x2="12" y2="12"></line></svg>'),ve=create_ssr_component((o,t,e,n)=>'<svg aria-label="undo" xmlns="http://www.w3.org/2000/svg" width="100%" height="100%" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" class="feather feather-rotate-ccw"><polyline points="1 4 1 10 7 10"></polyline><path d="M3.51 15a9 9 0 1 0 2.13-9.36L1 10"></path></svg>'),Y=create_ssr_component((o,t,e,n)=>'<svg xmlns="http://www.w3.org/2000/svg" width="90%" height="90%" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="feather feather-upload"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path><polyline points="17 8 12 3 7 8"></polyline><line x1="12" y1="3" x2="12" y2="15"></line></svg>'),pe=create_ssr_component((o,t,e,n)=>'<svg xmlns="http://www.w3.org/2000/svg" width="100%" height="100%" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" class="feather feather-video"><polygon points="23 7 16 12 23 17 23 7"></polygon><rect x="1" y="5" width="15" height="14" rx="2" ry="2"></rect></svg>'),we=create_ssr_component((o,t,e,n)=>'<svg width="100%" height="100%" viewBox="0 0 24 24" stroke-width="1.5" fill="none" xmlns="http://www.w3.org/2000/svg" stroke="currentColor" color="currentColor"><title>Low volume</title><path d="M19.5 7.5C19.5 7.5 21 9 21 11.5C21 14 19.5 15.5 19.5 15.5" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"></path><path d="M2 13.8571V10.1429C2 9.03829 2.89543 8.14286 4 8.14286H6.9C7.09569 8.14286 7.28708 8.08544 7.45046 7.97772L13.4495 4.02228C14.1144 3.5839 15 4.06075 15 4.85714V19.1429C15 19.9392 14.1144 20.4161 13.4495 19.9777L7.45046 16.0223C7.28708 15.9146 7.09569 15.8571 6.9 15.8571H4C2.89543 15.8571 2 14.9617 2 13.8571Z" stroke-width="1.5"></path></svg>'),fe=create_ssr_component((o,t,e,n)=>'<svg width="100%" height="100%" viewBox="0 0 24 24" stroke-width="1.5" fill="none" stroke="currentColor" xmlns="http://www.w3.org/2000/svg" color="currentColor"><title>High volume</title><path d="M1 13.8571V10.1429C1 9.03829 1.89543 8.14286 3 8.14286H5.9C6.09569 8.14286 6.28708 8.08544 6.45046 7.97772L12.4495 4.02228C13.1144 3.5839 14 4.06075 14 4.85714V19.1429C14 19.9392 13.1144 20.4161 12.4495 19.9777L6.45046 16.0223C6.28708 15.9146 6.09569 15.8571 5.9 15.8571H3C1.89543 15.8571 1 14.9617 1 13.8571Z" stroke-width="1.5"></path><path d="M17.5 7.5C17.5 7.5 19 9 19 11.5C19 14 17.5 15.5 17.5 15.5" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"></path><path d="M20.5 4.5C20.5 4.5 23 7 23 11.5C23 16 20.5 18.5 20.5 18.5" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"></path></svg>'),me=create_ssr_component((o,t,e,n)=>'<svg width="100%" height="100%" viewBox="0 0 24 24" stroke-width="1.5" fill="none" xmlns="http://www.w3.org/2000/svg" stroke="currentColor" color="currentColor"><title>Muted volume</title><g clip-path="url(#clip0_3173_16686)"><path d="M18 14L20.0005 12M22 10L20.0005 12M20.0005 12L18 10M20.0005 12L22 14" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"></path><path d="M2 13.8571V10.1429C2 9.03829 2.89543 8.14286 4 8.14286H6.9C7.09569 8.14286 7.28708 8.08544 7.45046 7.97772L13.4495 4.02228C14.1144 3.5839 15 4.06075 15 4.85714V19.1429C15 19.9392 14.1144 20.4161 13.4495 19.9777L7.45046 16.0223C7.28708 15.9146 7.09569 15.8571 6.9 15.8571H4C2.89543 15.8571 2 14.9617 2 13.8571Z" stroke-width="1.5"></path></g><defs><clipPath id="clip0_3173_16686"><rect width="24" height="24" fill="white"></rect></clipPath></defs></svg>'),xe=create_ssr_component((o,t,e,n)=>'<svg fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24" width="100%" height="100%" xmlns="http://www.w3.org/2000/svg" aria-hidden="true" stroke-linecap="round" stroke-linejoin="round"><path stroke-linecap="round" stroke-linejoin="round" d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126zM12 15.75h.007v.008H12v-.008z"></path></svg>'),st$1=create_ssr_component((o,t,e,n)=>'<svg xmlns="http://www.w3.org/2000/svg" width="100%" height="100%" viewBox="0 0 24 24"><path fill="currentColor" d="M12 2c-4.963 0-9 4.038-9 9c0 3.328 1.82 6.232 4.513 7.79l-2.067 1.378A1 1 0 0 0 6 22h12a1 1 0 0 0 .555-1.832l-2.067-1.378C19.18 17.232 21 14.328 21 11c0-4.962-4.037-9-9-9zm0 16c-3.859 0-7-3.141-7-7c0-3.86 3.141-7 7-7s7 3.14 7 7c0 3.859-3.141 7-7 7z"></path><path fill="currentColor" d="M12 6c-2.757 0-5 2.243-5 5s2.243 5 5 5s5-2.243 5-5s-2.243-5-5-5zm0 8c-1.654 0-3-1.346-3-3s1.346-3 3-3s3 1.346 3 3s-1.346 3-3 3z"></path></svg>'),at$1={code:"svg.svelte-184ngxt{animation:svelte-184ngxt-spin 1.5s linear infinite}@keyframes svelte-184ngxt-spin{0%{transform:rotate(0deg)}100%{transform:rotate(360deg)}}",map:'{"version":3,"file":"Spinner.svelte","sources":["Spinner.svelte"],"sourcesContent":["<svg\\n\\txmlns=\\"http://www.w3.org/2000/svg\\"\\n\\twidth=\\"100%\\"\\n\\theight=\\"100%\\"\\n\\tviewBox=\\"0 0 50 50\\"\\n>\\n\\t<circle\\n\\t\\tcx=\\"25\\"\\n\\t\\tcy=\\"25\\"\\n\\t\\tr=\\"20\\"\\n\\t\\tfill=\\"none\\"\\n\\t\\tstroke-width=\\"3.0\\"\\n\\t\\tstroke-linecap=\\"round\\"\\n\\t\\tstroke-dasharray=\\"94.2477796076938 94.2477796076938\\"\\n\\t\\tstroke-dashoffset=\\"0\\"\\n\\t>\\n\\t\\t<animateTransform\\n\\t\\t\\tattributeName=\\"transform\\"\\n\\t\\t\\ttype=\\"rotate\\"\\n\\t\\t\\tfrom=\\"0 25 25\\"\\n\\t\\t\\tto=\\"360 25 25\\"\\n\\t\\t\\trepeatCount=\\"indefinite\\"\\n\\t\\t/>\\n\\t</circle>\\n</svg>\\n\\n<style>\\n\\tsvg {\\n\\t\\tanimation: spin 1.5s linear infinite;\\n\\t}\\n\\n\\t@keyframes spin {\\n\\t\\t0% {\\n\\t\\t\\ttransform: rotate(0deg);\\n\\t\\t}\\n\\t\\t100% {\\n\\t\\t\\ttransform: rotate(360deg);\\n\\t\\t}\\n\\t}</style>\\n"],"names":[],"mappings":"AA2BC,kBAAI,CACH,SAAS,CAAE,mBAAI,CAAC,IAAI,CAAC,MAAM,CAAC,QAC7B,CAEA,WAAW,mBAAK,CACf,EAAG,CACF,SAAS,CAAE,OAAO,IAAI,CACvB,CACA,IAAK,CACJ,SAAS,CAAE,OAAO,MAAM,CACzB,CACD"}'},be=create_ssr_component((o,t,e,n)=>(o.css.add(at$1),'<svg xmlns="http://www.w3.org/2000/svg" width="100%" height="100%" viewBox="0 0 50 50" class="svelte-184ngxt"><circle cx="25" cy="25" r="20" fill="none" stroke-width="3.0" stroke-linecap="round" stroke-dasharray="94.2477796076938 94.2477796076938" stroke-dashoffset="0"><animateTransform attributeName="transform" type="rotate" from="0 25 25" to="360 25 25" repeatCount="indefinite"></animateTransform></circle></svg>')),Be=create_ssr_component((o,t,e,n)=>'<svg width="100%" height="100%" stroke-width="1.5" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" color="currentColor"><path d="M19.1679 9C18.0247 6.46819 15.3006 4.5 11.9999 4.5C8.31459 4.5 5.05104 7.44668 4.54932 11" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"></path><path d="M16 9H19.4C19.7314 9 20 8.73137 20 8.4V5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"></path><path d="M4.88146 15C5.92458 17.5318 8.64874 19.5 12.0494 19.5C15.7347 19.5 18.9983 16.5533 19.5 13" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"></path><path d="M8.04932 15H4.64932C4.31795 15 4.04932 15.2686 4.04932 15.6V19" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"></path></svg>');const ze=create_ssr_component((o,t,e,n)=>{createEventDispatcher();let{formatter:l}=t,{value:A}=t,{i18n:i}=t,s=!1;return t.formatter===void 0&&e.formatter&&l!==void 0&&e.formatter(l),t.value===void 0&&e.value&&A!==void 0&&e.value(A),t.i18n===void 0&&e.i18n&&i!==void 0&&e.i18n(i),`${validate_component(j,"IconButton").$$render(o,{Icon:ot$1,label:i("common.share"),pending:s},{},{})}`}),dt$1=/^(#\s*)(.+)$/m;function ct$1(o){const t=o.trim(),e=t.match(dt$1);if(!e)return [!1,t||!1];const[n,,l]=e,A=l.trim();if(t===n)return [A,!1];const i=e.index!==void 0?e.index+n.length:0,a=t.substring(i).trim()||!1;return [A,a]}const Ct$1={code:"h2.svelte-12ioyct{font-size:var(--text-xl) !important}p.svelte-12ioyct,h2.svelte-12ioyct{white-space:pre-line}.wrap.svelte-12ioyct{display:flex;flex-direction:column;justify-content:center;align-items:center;min-height:var(--size-60);color:var(--block-label-text-color);line-height:var(--line-md);height:100%;padding-top:var(--size-3);text-align:center;margin:auto var(--spacing-lg)}.or.svelte-12ioyct{color:var(--body-text-color-subdued);display:flex}.icon-wrap.svelte-12ioyct{width:30px;margin-bottom:var(--spacing-lg)}@media(min-width: 768px){.wrap.svelte-12ioyct{font-size:var(--text-lg)}}.hovered.svelte-12ioyct{color:var(--color-accent)}",map:'{"version":3,"file":"UploadText.svelte","sources":["UploadText.svelte"],"sourcesContent":["<script lang=\\"ts\\">import { Upload as UploadIcon, ImagePaste } from \\"@gradio/icons\\";\\nimport { inject } from \\"./utils/parse_placeholder\\";\\nexport let type = \\"file\\";\\nexport let i18n;\\nexport let message = void 0;\\nexport let mode = \\"full\\";\\nexport let hovered = false;\\nexport let placeholder = void 0;\\nconst defs = {\\n    image: \\"upload_text.drop_image\\",\\n    video: \\"upload_text.drop_video\\",\\n    audio: \\"upload_text.drop_audio\\",\\n    file: \\"upload_text.drop_file\\",\\n    csv: \\"upload_text.drop_csv\\",\\n    gallery: \\"upload_text.drop_gallery\\",\\n    clipboard: \\"upload_text.paste_clipboard\\"\\n};\\n$: [heading, paragraph] = placeholder ? inject(placeholder) : [false, false];\\n<\/script>\\n\\n<div class=\\"wrap\\">\\n\\t<span class=\\"icon-wrap\\" class:hovered>\\n\\t\\t{#if type === \\"clipboard\\"}\\n\\t\\t\\t<ImagePaste />\\n\\t\\t{:else}\\n\\t\\t\\t<UploadIcon />\\n\\t\\t{/if}\\n\\t</span>\\n\\n\\t{#if heading || paragraph}\\n\\t\\t{#if heading}\\n\\t\\t\\t<h2>{heading}</h2>\\n\\t\\t{/if}\\n\\t\\t{#if paragraph}\\n\\t\\t\\t<p>{paragraph}</p>\\n\\t\\t{/if}\\n\\t{:else}\\n\\t\\t{i18n(defs[type] || defs.file)}\\n\\n\\t\\t{#if mode !== \\"short\\"}\\n\\t\\t\\t<span class=\\"or\\">- {i18n(\\"common.or\\")} -</span>\\n\\t\\t\\t{message || i18n(\\"upload_text.click_to_upload\\")}\\n\\t\\t{/if}\\n\\t{/if}\\n</div>\\n\\n<style>\\n\\th2 {\\n\\t\\tfont-size: var(--text-xl) !important;\\n\\t}\\n\\n\\tp,\\n\\th2 {\\n\\t\\twhite-space: pre-line;\\n\\t}\\n\\n\\t.wrap {\\n\\t\\tdisplay: flex;\\n\\t\\tflex-direction: column;\\n\\t\\tjustify-content: center;\\n\\t\\talign-items: center;\\n\\t\\tmin-height: var(--size-60);\\n\\t\\tcolor: var(--block-label-text-color);\\n\\t\\tline-height: var(--line-md);\\n\\t\\theight: 100%;\\n\\t\\tpadding-top: var(--size-3);\\n\\t\\ttext-align: center;\\n\\t\\tmargin: auto var(--spacing-lg);\\n\\t}\\n\\n\\t.or {\\n\\t\\tcolor: var(--body-text-color-subdued);\\n\\t\\tdisplay: flex;\\n\\t}\\n\\n\\t.icon-wrap {\\n\\t\\twidth: 30px;\\n\\t\\tmargin-bottom: var(--spacing-lg);\\n\\t}\\n\\n\\t@media (min-width: 768px) {\\n\\t\\t.wrap {\\n\\t\\t\\tfont-size: var(--text-lg);\\n\\t\\t}\\n\\t}\\n\\n\\t.hovered {\\n\\t\\tcolor: var(--color-accent);\\n\\t}</style>\\n"],"names":[],"mappings":"AA+CC,iBAAG,CACF,SAAS,CAAE,IAAI,SAAS,CAAC,CAAC,UAC3B,CAEA,gBAAC,CACD,iBAAG,CACF,WAAW,CAAE,QACd,CAEA,oBAAM,CACL,OAAO,CAAE,IAAI,CACb,cAAc,CAAE,MAAM,CACtB,eAAe,CAAE,MAAM,CACvB,WAAW,CAAE,MAAM,CACnB,UAAU,CAAE,IAAI,SAAS,CAAC,CAC1B,KAAK,CAAE,IAAI,wBAAwB,CAAC,CACpC,WAAW,CAAE,IAAI,SAAS,CAAC,CAC3B,MAAM,CAAE,IAAI,CACZ,WAAW,CAAE,IAAI,QAAQ,CAAC,CAC1B,UAAU,CAAE,MAAM,CAClB,MAAM,CAAE,IAAI,CAAC,IAAI,YAAY,CAC9B,CAEA,kBAAI,CACH,KAAK,CAAE,IAAI,yBAAyB,CAAC,CACrC,OAAO,CAAE,IACV,CAEA,yBAAW,CACV,KAAK,CAAE,IAAI,CACX,aAAa,CAAE,IAAI,YAAY,CAChC,CAEA,MAAO,YAAY,KAAK,CAAE,CACzB,oBAAM,CACL,SAAS,CAAE,IAAI,SAAS,CACzB,CACD,CAEA,uBAAS,CACR,KAAK,CAAE,IAAI,cAAc,CAC1B"}'},Ke=create_ssr_component((o,t,e,n)=>{let l,A,{type:i="file"}=t,{i18n:s}=t,{message:a=void 0}=t,{mode:d="full"}=t,{hovered:g=!1}=t,{placeholder:h=void 0}=t;const p={image:"upload_text.drop_image",video:"upload_text.drop_video",audio:"upload_text.drop_audio",file:"upload_text.drop_file",csv:"upload_text.drop_csv",gallery:"upload_text.drop_gallery",clipboard:"upload_text.paste_clipboard"};return t.type===void 0&&e.type&&i!==void 0&&e.type(i),t.i18n===void 0&&e.i18n&&s!==void 0&&e.i18n(s),t.message===void 0&&e.message&&a!==void 0&&e.message(a),t.mode===void 0&&e.mode&&d!==void 0&&e.mode(d),t.hovered===void 0&&e.hovered&&g!==void 0&&e.hovered(g),t.placeholder===void 0&&e.placeholder&&h!==void 0&&e.placeholder(h),o.css.add(Ct$1),[l,A]=h?ct$1(h):[!1,!1],`<div class="wrap svelte-12ioyct"><span class="${["icon-wrap svelte-12ioyct",g?"hovered":""].join(" ").trim()}">${i==="clipboard"?`${validate_component(H,"ImagePaste").$$render(o,{},{},{})}`:`${validate_component(Y,"UploadIcon").$$render(o,{},{},{})}`}</span> ${l||A?`${l?`<h2 class="svelte-12ioyct">${escape(l)}</h2>`:""} ${A?`<p class="svelte-12ioyct">${escape(A)}</p>`:""}`:`${escape(s(p[i]||p.file))} ${d!=="short"?`<span class="or svelte-12ioyct">- ${escape(s("common.or"))} -</span> ${escape(a||s("upload_text.click_to_upload"))}`:""}`} </div>`});const vt$1={code:".source-selection.svelte-snayfm{display:flex;align-items:center;justify-content:center;border-top:1px solid var(--border-color-primary);width:100%;margin-left:auto;margin-right:auto;height:var(--size-10)}.icon.svelte-snayfm{width:22px;height:22px;margin:var(--spacing-lg) var(--spacing-xs);padding:var(--spacing-xs);color:var(--neutral-400);border-radius:var(--radius-md)}.selected.svelte-snayfm{color:var(--color-accent)}.icon.svelte-snayfm:hover,.icon.svelte-snayfm:focus{color:var(--color-accent)}",map:'{"version":3,"file":"SelectSource.svelte","sources":["SelectSource.svelte"],"sourcesContent":["<script lang=\\"ts\\">import { Microphone, Upload, Webcam, ImagePaste } from \\"@gradio/icons\\";\\nexport let sources;\\nexport let active_source;\\nexport let handle_clear = () => {\\n};\\nexport let handle_select = () => {\\n};\\n$: unique_sources = [...new Set(sources)];\\nasync function handle_select_source(source) {\\n    handle_clear();\\n    active_source = source;\\n    handle_select(source);\\n}\\n<\/script>\\n\\n{#if unique_sources.length > 1}\\n\\t<span class=\\"source-selection\\" data-testid=\\"source-select\\">\\n\\t\\t{#if sources.includes(\\"upload\\")}\\n\\t\\t\\t<button\\n\\t\\t\\t\\tclass=\\"icon\\"\\n\\t\\t\\t\\tclass:selected={active_source === \\"upload\\" || !active_source}\\n\\t\\t\\t\\taria-label=\\"Upload file\\"\\n\\t\\t\\t\\ton:click={() => handle_select_source(\\"upload\\")}><Upload /></button\\n\\t\\t\\t>\\n\\t\\t{/if}\\n\\n\\t\\t{#if sources.includes(\\"microphone\\")}\\n\\t\\t\\t<button\\n\\t\\t\\t\\tclass=\\"icon\\"\\n\\t\\t\\t\\tclass:selected={active_source === \\"microphone\\"}\\n\\t\\t\\t\\taria-label=\\"Record audio\\"\\n\\t\\t\\t\\ton:click={() => handle_select_source(\\"microphone\\")}\\n\\t\\t\\t\\t><Microphone /></button\\n\\t\\t\\t>\\n\\t\\t{/if}\\n\\n\\t\\t{#if sources.includes(\\"webcam\\")}\\n\\t\\t\\t<button\\n\\t\\t\\t\\tclass=\\"icon\\"\\n\\t\\t\\t\\tclass:selected={active_source === \\"webcam\\"}\\n\\t\\t\\t\\taria-label=\\"Capture from camera\\"\\n\\t\\t\\t\\ton:click={() => handle_select_source(\\"webcam\\")}><Webcam /></button\\n\\t\\t\\t>\\n\\t\\t{/if}\\n\\t\\t{#if sources.includes(\\"clipboard\\")}\\n\\t\\t\\t<button\\n\\t\\t\\t\\tclass=\\"icon\\"\\n\\t\\t\\t\\tclass:selected={active_source === \\"clipboard\\"}\\n\\t\\t\\t\\taria-label=\\"Paste from clipboard\\"\\n\\t\\t\\t\\ton:click={() => handle_select_source(\\"clipboard\\")}\\n\\t\\t\\t\\t><ImagePaste /></button\\n\\t\\t\\t>\\n\\t\\t{/if}\\n\\t</span>\\n{/if}\\n\\n<style>\\n\\t.source-selection {\\n\\t\\tdisplay: flex;\\n\\t\\talign-items: center;\\n\\t\\tjustify-content: center;\\n\\t\\tborder-top: 1px solid var(--border-color-primary);\\n\\t\\twidth: 100%;\\n\\t\\tmargin-left: auto;\\n\\t\\tmargin-right: auto;\\n\\t\\theight: var(--size-10);\\n\\t}\\n\\n\\t.icon {\\n\\t\\twidth: 22px;\\n\\t\\theight: 22px;\\n\\t\\tmargin: var(--spacing-lg) var(--spacing-xs);\\n\\t\\tpadding: var(--spacing-xs);\\n\\t\\tcolor: var(--neutral-400);\\n\\t\\tborder-radius: var(--radius-md);\\n\\t}\\n\\n\\t.selected {\\n\\t\\tcolor: var(--color-accent);\\n\\t}\\n\\n\\t.icon:hover,\\n\\t.icon:focus {\\n\\t\\tcolor: var(--color-accent);\\n\\t}</style>\\n"],"names":[],"mappings":"AAyDC,+BAAkB,CACjB,OAAO,CAAE,IAAI,CACb,WAAW,CAAE,MAAM,CACnB,eAAe,CAAE,MAAM,CACvB,UAAU,CAAE,GAAG,CAAC,KAAK,CAAC,IAAI,sBAAsB,CAAC,CACjD,KAAK,CAAE,IAAI,CACX,WAAW,CAAE,IAAI,CACjB,YAAY,CAAE,IAAI,CAClB,MAAM,CAAE,IAAI,SAAS,CACtB,CAEA,mBAAM,CACL,KAAK,CAAE,IAAI,CACX,MAAM,CAAE,IAAI,CACZ,MAAM,CAAE,IAAI,YAAY,CAAC,CAAC,IAAI,YAAY,CAAC,CAC3C,OAAO,CAAE,IAAI,YAAY,CAAC,CAC1B,KAAK,CAAE,IAAI,aAAa,CAAC,CACzB,aAAa,CAAE,IAAI,WAAW,CAC/B,CAEA,uBAAU,CACT,KAAK,CAAE,IAAI,cAAc,CAC1B,CAEA,mBAAK,MAAM,CACX,mBAAK,MAAO,CACX,KAAK,CAAE,IAAI,cAAc,CAC1B"}'},Le$1=create_ssr_component((o,t,e,n)=>{let l,{sources:A}=t,{active_source:i}=t,{handle_clear:s=()=>{}}=t,{handle_select:a=()=>{}}=t;return t.sources===void 0&&e.sources&&A!==void 0&&e.sources(A),t.active_source===void 0&&e.active_source&&i!==void 0&&e.active_source(i),t.handle_clear===void 0&&e.handle_clear&&s!==void 0&&e.handle_clear(s),t.handle_select===void 0&&e.handle_select&&a!==void 0&&e.handle_select(a),o.css.add(vt$1),l=[...new Set(A)],`${l.length>1?`<span class="source-selection svelte-snayfm" data-testid="source-select">${A.includes("upload")?`<button class="${["icon svelte-snayfm",i==="upload"||!i?"selected":""].join(" ").trim()}" aria-label="Upload file">${validate_component(Y,"Upload").$$render(o,{},{},{})}</button>`:""} ${A.includes("microphone")?`<button class="${["icon svelte-snayfm",i==="microphone"?"selected":""].join(" ").trim()}" aria-label="Record audio">${validate_component(At,"Microphone").$$render(o,{},{},{})}</button>`:""} ${A.includes("webcam")?`<button class="${["icon svelte-snayfm",i==="webcam"?"selected":""].join(" ").trim()}" aria-label="Capture from camera">${validate_component(st$1,"Webcam").$$render(o,{},{},{})}</button>`:""} ${A.includes("clipboard")?`<button class="${["icon svelte-snayfm",i==="clipboard"?"selected":""].join(" ").trim()}" aria-label="Paste from clipboard">${validate_component(H,"ImagePaste").$$render(o,{},{},{})}</button>`:""}</span>`:""}`}),pt={code:'.icon-button-wrapper.svelte-ud4hud{display:flex;flex-direction:row;align-items:center;justify-content:center;z-index:var(--layer-2);gap:var(--spacing-sm);box-shadow:var(--shadow-drop);border:1px solid var(--border-color-primary);background:var(--block-background-fill);padding:var(--spacing-xxs)}.icon-button-wrapper.hide-top-corner.svelte-ud4hud{border-top:none;border-right:none;border-radius:var(--block-label-right-radius)}.icon-button-wrapper.display-top-corner.svelte-ud4hud{border-radius:var(--radius-sm) 0 0 var(--radius-sm);top:var(--spacing-sm);right:-1px}.icon-button-wrapper.svelte-ud4hud:not(.top-panel){border:1px solid var(--border-color-primary);border-radius:var(--radius-sm)}.top-panel.svelte-ud4hud{position:absolute;top:var(--block-label-margin);right:var(--block-label-margin);margin:0}.icon-button-wrapper.svelte-ud4hud button{margin:var(--spacing-xxs);border-radius:var(--radius-xs);position:relative}.icon-button-wrapper.svelte-ud4hud a.download-link:not(:last-child),.icon-button-wrapper.svelte-ud4hud button:not(:last-child){margin-right:var(--spacing-xxs)}.icon-button-wrapper.svelte-ud4hud a.download-link:not(:last-child):not(.no-border *)::after,.icon-button-wrapper.svelte-ud4hud button:not(:last-child):not(.no-border *)::after{content:"";position:absolute;right:-4.5px;top:15%;height:70%;width:1px;background-color:var(--border-color-primary)}.icon-button-wrapper.svelte-ud4hud > *{height:100%}',map:'{"version":3,"file":"IconButtonWrapper.svelte","sources":["IconButtonWrapper.svelte"],"sourcesContent":["<script>\\n\\texport let top_panel = true;\\n\\texport let display_top_corner = false;\\n<\/script>\\n\\n<div\\n\\tclass={`icon-button-wrapper ${top_panel ? \\"top-panel\\" : \\"\\"} ${display_top_corner ? \\"display-top-corner\\" : \\"hide-top-corner\\"}`}\\n>\\n\\t<slot></slot>\\n</div>\\n\\n<style>\\n\\t.icon-button-wrapper {\\n\\t\\tdisplay: flex;\\n\\t\\tflex-direction: row;\\n\\t\\talign-items: center;\\n\\t\\tjustify-content: center;\\n\\t\\tz-index: var(--layer-2);\\n\\t\\tgap: var(--spacing-sm);\\n\\t\\tbox-shadow: var(--shadow-drop);\\n\\t\\tborder: 1px solid var(--border-color-primary);\\n\\t\\tbackground: var(--block-background-fill);\\n\\t\\tpadding: var(--spacing-xxs);\\n\\t}\\n\\n\\t.icon-button-wrapper.hide-top-corner {\\n\\t\\tborder-top: none;\\n\\t\\tborder-right: none;\\n\\t\\tborder-radius: var(--block-label-right-radius);\\n\\t}\\n\\n\\t.icon-button-wrapper.display-top-corner {\\n\\t\\tborder-radius: var(--radius-sm) 0 0 var(--radius-sm);\\n\\t\\ttop: var(--spacing-sm);\\n\\t\\tright: -1px;\\n\\t}\\n\\n\\t.icon-button-wrapper:not(.top-panel) {\\n\\t\\tborder: 1px solid var(--border-color-primary);\\n\\t\\tborder-radius: var(--radius-sm);\\n\\t}\\n\\n\\t.top-panel {\\n\\t\\tposition: absolute;\\n\\t\\ttop: var(--block-label-margin);\\n\\t\\tright: var(--block-label-margin);\\n\\t\\tmargin: 0;\\n\\t}\\n\\n\\t.icon-button-wrapper :global(button) {\\n\\t\\tmargin: var(--spacing-xxs);\\n\\t\\tborder-radius: var(--radius-xs);\\n\\t\\tposition: relative;\\n\\t}\\n\\n\\t.icon-button-wrapper :global(a.download-link:not(:last-child)),\\n\\t.icon-button-wrapper :global(button:not(:last-child)) {\\n\\t\\tmargin-right: var(--spacing-xxs);\\n\\t}\\n\\n\\t.icon-button-wrapper\\n\\t\\t:global(a.download-link:not(:last-child):not(.no-border *)::after),\\n\\t.icon-button-wrapper\\n\\t\\t:global(button:not(:last-child):not(.no-border *)::after) {\\n\\t\\tcontent: \\"\\";\\n\\t\\tposition: absolute;\\n\\t\\tright: -4.5px;\\n\\t\\ttop: 15%;\\n\\t\\theight: 70%;\\n\\t\\twidth: 1px;\\n\\t\\tbackground-color: var(--border-color-primary);\\n\\t}\\n\\n\\t.icon-button-wrapper :global(> *) {\\n\\t\\theight: 100%;\\n\\t}</style>\\n"],"names":[],"mappings":"AAYC,kCAAqB,CACpB,OAAO,CAAE,IAAI,CACb,cAAc,CAAE,GAAG,CACnB,WAAW,CAAE,MAAM,CACnB,eAAe,CAAE,MAAM,CACvB,OAAO,CAAE,IAAI,SAAS,CAAC,CACvB,GAAG,CAAE,IAAI,YAAY,CAAC,CACtB,UAAU,CAAE,IAAI,aAAa,CAAC,CAC9B,MAAM,CAAE,GAAG,CAAC,KAAK,CAAC,IAAI,sBAAsB,CAAC,CAC7C,UAAU,CAAE,IAAI,uBAAuB,CAAC,CACxC,OAAO,CAAE,IAAI,aAAa,CAC3B,CAEA,oBAAoB,8BAAiB,CACpC,UAAU,CAAE,IAAI,CAChB,YAAY,CAAE,IAAI,CAClB,aAAa,CAAE,IAAI,0BAA0B,CAC9C,CAEA,oBAAoB,iCAAoB,CACvC,aAAa,CAAE,IAAI,WAAW,CAAC,CAAC,CAAC,CAAC,CAAC,CAAC,IAAI,WAAW,CAAC,CACpD,GAAG,CAAE,IAAI,YAAY,CAAC,CACtB,KAAK,CAAE,IACR,CAEA,kCAAoB,KAAK,UAAU,CAAE,CACpC,MAAM,CAAE,GAAG,CAAC,KAAK,CAAC,IAAI,sBAAsB,CAAC,CAC7C,aAAa,CAAE,IAAI,WAAW,CAC/B,CAEA,wBAAW,CACV,QAAQ,CAAE,QAAQ,CAClB,GAAG,CAAE,IAAI,oBAAoB,CAAC,CAC9B,KAAK,CAAE,IAAI,oBAAoB,CAAC,CAChC,MAAM,CAAE,CACT,CAEA,kCAAoB,CAAS,MAAQ,CACpC,MAAM,CAAE,IAAI,aAAa,CAAC,CAC1B,aAAa,CAAE,IAAI,WAAW,CAAC,CAC/B,QAAQ,CAAE,QACX,CAEA,kCAAoB,CAAS,gCAAiC,CAC9D,kCAAoB,CAAS,uBAAyB,CACrD,YAAY,CAAE,IAAI,aAAa,CAChC,CAEA,kCAAoB,CACX,yDAA0D,CACnE,kCAAoB,CACX,gDAAkD,CAC1D,OAAO,CAAE,EAAE,CACX,QAAQ,CAAE,QAAQ,CAClB,KAAK,CAAE,MAAM,CACb,GAAG,CAAE,GAAG,CACR,MAAM,CAAE,GAAG,CACX,KAAK,CAAE,GAAG,CACV,gBAAgB,CAAE,IAAI,sBAAsB,CAC7C,CAEA,kCAAoB,CAAS,GAAK,CACjC,MAAM,CAAE,IACT"}'},We=create_ssr_component((o,t,e,n)=>{let{top_panel:l=!0}=t,{display_top_corner:A=!1}=t;return t.top_panel===void 0&&e.top_panel&&l!==void 0&&e.top_panel(l),t.display_top_corner===void 0&&e.display_top_corner&&A!==void 0&&e.display_top_corner(A),o.css.add(pt),`<div class="${escape(null_to_empty(`icon-button-wrapper ${l?"top-panel":""} ${A?"display-top-corner":"hide-top-corner"}`),!0)+" svelte-ud4hud"}">${n.default?n.default({}):""} </div>`}),qe=create_ssr_component((o,t,e,n)=>{createEventDispatcher();let{fullscreen:l}=t;return t.fullscreen===void 0&&e.fullscreen&&l!==void 0&&e.fullscreen(l),`${l?`${validate_component(j,"IconButton").$$render(o,{Icon:it$2,label:"Exit fullscreen mode"},{},{})}`:`${validate_component(j,"IconButton").$$render(o,{Icon:lt$2,label:"Fullscreen"},{},{})}`}`});

function S(e){let A=["","k","M","G","T","P","E","Z"],t=0;for(;e>1e3&&t<A.length-1;)e/=1e3,t++;let m=A[t];return (Number.isInteger(e)?e:e.toFixed(1))+m}const nt={code:"svg.svelte-zyxd38.svelte-zyxd38{width:var(--size-20);height:var(--size-20)}svg.svelte-zyxd38 path.svelte-zyxd38{fill:var(--loader-color)}div.svelte-zyxd38.svelte-zyxd38{z-index:var(--layer-2)}.margin.svelte-zyxd38.svelte-zyxd38{margin:var(--size-4)}",map:'{"version":3,"file":"Loader.svelte","sources":["Loader.svelte"],"sourcesContent":["<script lang=\\"ts\\">import { onMount } from \\"svelte\\";\\nimport { spring } from \\"svelte/motion\\";\\nexport let margin = true;\\nconst top = spring([0, 0]);\\nconst bottom = spring([0, 0]);\\nlet dismounted;\\nasync function animate() {\\n    await Promise.all([top.set([125, 140]), bottom.set([-125, -140])]);\\n    await Promise.all([top.set([-125, 140]), bottom.set([125, -140])]);\\n    await Promise.all([top.set([-125, 0]), bottom.set([125, -0])]);\\n    await Promise.all([top.set([125, 0]), bottom.set([-125, 0])]);\\n}\\nasync function run() {\\n    await animate();\\n    if (!dismounted)\\n        run();\\n}\\nasync function loading() {\\n    await Promise.all([top.set([125, 0]), bottom.set([-125, 0])]);\\n    run();\\n}\\nonMount(() => {\\n    loading();\\n    return () => dismounted = true;\\n});\\n<\/script>\\n\\n<div class:margin>\\n\\t<svg\\n\\t\\tviewBox=\\"-1200 -1200 3000 3000\\"\\n\\t\\tfill=\\"none\\"\\n\\t\\txmlns=\\"http://www.w3.org/2000/svg\\"\\n\\t>\\n\\t\\t<g style=\\"transform: translate({$top[0]}px, {$top[1]}px);\\">\\n\\t\\t\\t<path\\n\\t\\t\\t\\td=\\"M255.926 0.754768L509.702 139.936V221.027L255.926 81.8465V0.754768Z\\"\\n\\t\\t\\t\\tfill=\\"#FF7C00\\"\\n\\t\\t\\t\\tfill-opacity=\\"0.4\\"\\n\\t\\t\\t/>\\n\\t\\t\\t<path\\n\\t\\t\\t\\td=\\"M509.69 139.936L254.981 279.641V361.255L509.69 221.55V139.936Z\\"\\n\\t\\t\\t\\tfill=\\"#FF7C00\\"\\n\\t\\t\\t/>\\n\\t\\t\\t<path\\n\\t\\t\\t\\td=\\"M0.250138 139.937L254.981 279.641V361.255L0.250138 221.55V139.937Z\\"\\n\\t\\t\\t\\tfill=\\"#FF7C00\\"\\n\\t\\t\\t\\tfill-opacity=\\"0.4\\"\\n\\t\\t\\t/>\\n\\t\\t\\t<path\\n\\t\\t\\t\\td=\\"M255.923 0.232622L0.236328 139.936V221.55L255.923 81.8469V0.232622Z\\"\\n\\t\\t\\t\\tfill=\\"#FF7C00\\"\\n\\t\\t\\t/>\\n\\t\\t</g>\\n\\t\\t<g style=\\"transform: translate({$bottom[0]}px, {$bottom[1]}px);\\">\\n\\t\\t\\t<path\\n\\t\\t\\t\\td=\\"M255.926 141.5L509.702 280.681V361.773L255.926 222.592V141.5Z\\"\\n\\t\\t\\t\\tfill=\\"#FF7C00\\"\\n\\t\\t\\t\\tfill-opacity=\\"0.4\\"\\n\\t\\t\\t/>\\n\\t\\t\\t<path\\n\\t\\t\\t\\td=\\"M509.69 280.679L254.981 420.384V501.998L509.69 362.293V280.679Z\\"\\n\\t\\t\\t\\tfill=\\"#FF7C00\\"\\n\\t\\t\\t/>\\n\\t\\t\\t<path\\n\\t\\t\\t\\td=\\"M0.250138 280.681L254.981 420.386V502L0.250138 362.295V280.681Z\\"\\n\\t\\t\\t\\tfill=\\"#FF7C00\\"\\n\\t\\t\\t\\tfill-opacity=\\"0.4\\"\\n\\t\\t\\t/>\\n\\t\\t\\t<path\\n\\t\\t\\t\\td=\\"M255.923 140.977L0.236328 280.68V362.294L255.923 222.591V140.977Z\\"\\n\\t\\t\\t\\tfill=\\"#FF7C00\\"\\n\\t\\t\\t/>\\n\\t\\t</g>\\n\\t</svg>\\n</div>\\n\\n<style>\\n\\tsvg {\\n\\t\\twidth: var(--size-20);\\n\\t\\theight: var(--size-20);\\n\\t}\\n\\n\\tsvg path {\\n\\t\\tfill: var(--loader-color);\\n\\t}\\n\\n\\tdiv {\\n\\t\\tz-index: var(--layer-2);\\n\\t}\\n\\n\\t.margin {\\n\\t\\tmargin: var(--size-4);\\n\\t}</style>\\n"],"names":[],"mappings":"AA6EC,+BAAI,CACH,KAAK,CAAE,IAAI,SAAS,CAAC,CACrB,MAAM,CAAE,IAAI,SAAS,CACtB,CAEA,iBAAG,CAAC,kBAAK,CACR,IAAI,CAAE,IAAI,cAAc,CACzB,CAEA,+BAAI,CACH,OAAO,CAAE,IAAI,SAAS,CACvB,CAEA,mCAAQ,CACP,MAAM,CAAE,IAAI,QAAQ,CACrB"}'},rt=create_ssr_component((e,A,t,m)=>{let a,c,l,i,{margin:r=!0}=A;const o=spring([0,0]);c=subscribe(o,v=>a=v);const s=spring([0,0]);i=subscribe(s,v=>l=v);return A.margin===void 0&&t.margin&&r!==void 0&&t.margin(r),e.css.add(nt),c(),i(),`<div class="${["svelte-zyxd38",r?"margin":""].join(" ").trim()}"><svg viewBox="-1200 -1200 3000 3000" fill="none" xmlns="http://www.w3.org/2000/svg" class="svelte-zyxd38"><g style="${"transform: translate("+escape(a[0],!0)+"px, "+escape(a[1],!0)+"px);"}"><path d="M255.926 0.754768L509.702 139.936V221.027L255.926 81.8465V0.754768Z" fill="#FF7C00" fill-opacity="0.4" class="svelte-zyxd38"></path><path d="M509.69 139.936L254.981 279.641V361.255L509.69 221.55V139.936Z" fill="#FF7C00" class="svelte-zyxd38"></path><path d="M0.250138 139.937L254.981 279.641V361.255L0.250138 221.55V139.937Z" fill="#FF7C00" fill-opacity="0.4" class="svelte-zyxd38"></path><path d="M255.923 0.232622L0.236328 139.936V221.55L255.923 81.8469V0.232622Z" fill="#FF7C00" class="svelte-zyxd38"></path></g><g style="${"transform: translate("+escape(l[0],!0)+"px, "+escape(l[1],!0)+"px);"}"><path d="M255.926 141.5L509.702 280.681V361.773L255.926 222.592V141.5Z" fill="#FF7C00" fill-opacity="0.4" class="svelte-zyxd38"></path><path d="M509.69 280.679L254.981 420.384V501.998L509.69 362.293V280.679Z" fill="#FF7C00" class="svelte-zyxd38"></path><path d="M0.250138 280.681L254.981 420.386V502L0.250138 362.295V280.681Z" fill="#FF7C00" fill-opacity="0.4" class="svelte-zyxd38"></path><path d="M255.923 140.977L0.236328 280.68V362.294L255.923 222.591V140.977Z" fill="#FF7C00" class="svelte-zyxd38"></path></g></svg> </div>`}),ot={code:`.wrap.svelte-ls20lj.svelte-ls20lj{display:flex;flex-direction:column;justify-content:center;align-items:center;z-index:var(--layer-2);transition:opacity 0.1s ease-in-out;border-radius:var(--block-radius);background:var(--block-background-fill);padding:0 var(--size-6);max-height:var(--size-screen-h);overflow:hidden}.wrap.center.svelte-ls20lj.svelte-ls20lj{top:0;right:0px;left:0px}.wrap.default.svelte-ls20lj.svelte-ls20lj{top:0px;right:0px;bottom:0px;left:0px}.hide.svelte-ls20lj.svelte-ls20lj{opacity:0;pointer-events:none}.generating.svelte-ls20lj.svelte-ls20lj{animation:svelte-ls20lj-pulseStart 1s cubic-bezier(0.4, 0, 0.6, 1),
			svelte-ls20lj-pulse 2s cubic-bezier(0.4, 0, 0.6, 1) 1s infinite;border:2px solid var(--color-accent);background:transparent;z-index:var(--layer-1);pointer-events:none}.translucent.svelte-ls20lj.svelte-ls20lj{background:none}@keyframes svelte-ls20lj-pulseStart{0%{opacity:0}100%{opacity:1}}@keyframes svelte-ls20lj-pulse{0%,100%{opacity:1}50%{opacity:0.5}}.loading.svelte-ls20lj.svelte-ls20lj{z-index:var(--layer-2);color:var(--body-text-color)}.eta-bar.svelte-ls20lj.svelte-ls20lj{position:absolute;top:0;right:0;bottom:0;left:0;transform-origin:left;opacity:0.8;z-index:var(--layer-1);transition:10ms;background:var(--background-fill-secondary)}.progress-bar-wrap.svelte-ls20lj.svelte-ls20lj{border:1px solid var(--border-color-primary);background:var(--background-fill-primary);width:55.5%;height:var(--size-4)}.progress-bar.svelte-ls20lj.svelte-ls20lj{transform-origin:left;background-color:var(--loader-color);width:var(--size-full);height:var(--size-full)}.progress-level.svelte-ls20lj.svelte-ls20lj{display:flex;flex-direction:column;align-items:center;gap:1;z-index:var(--layer-2);width:var(--size-full)}.progress-level-inner.svelte-ls20lj.svelte-ls20lj{margin:var(--size-2) auto;color:var(--body-text-color);font-size:var(--text-sm);font-family:var(--font-mono)}.meta-text.svelte-ls20lj.svelte-ls20lj{position:absolute;bottom:0;right:0;z-index:var(--layer-2);padding:var(--size-1) var(--size-2);font-size:var(--text-sm);font-family:var(--font-mono)}.meta-text-center.svelte-ls20lj.svelte-ls20lj{display:flex;position:absolute;top:0;right:0;justify-content:center;align-items:center;transform:translateY(var(--size-6));z-index:var(--layer-2);padding:var(--size-1) var(--size-2);font-size:var(--text-sm);font-family:var(--font-mono);text-align:center}.error.svelte-ls20lj.svelte-ls20lj{box-shadow:var(--shadow-drop);border:solid 1px var(--error-border-color);border-radius:var(--radius-full);background:var(--error-background-fill);padding-right:var(--size-4);padding-left:var(--size-4);color:var(--error-text-color);font-weight:var(--weight-semibold);font-size:var(--text-lg);line-height:var(--line-lg);font-family:var(--font)}.minimal.svelte-ls20lj.svelte-ls20lj{pointer-events:none}.minimal.svelte-ls20lj .progress-text.svelte-ls20lj{background:var(--block-background-fill)}.border.svelte-ls20lj.svelte-ls20lj{border:1px solid var(--border-color-primary)}.clear-status.svelte-ls20lj.svelte-ls20lj{position:absolute;display:flex;top:var(--size-2);right:var(--size-2);justify-content:flex-end;gap:var(--spacing-sm);z-index:var(--layer-1)}`,map:'{"version":3,"file":"index.svelte","sources":["index.svelte"],"sourcesContent":["<script context=\\"module\\" lang=\\"ts\\">import { tick } from \\"svelte\\";\\nimport { pretty_si } from \\"./utils\\";\\nlet items = [];\\nlet called = false;\\nconst is_browser = typeof window !== \\"undefined\\";\\nconst raf = is_browser ? window.requestAnimationFrame : (cb) => {\\n};\\nasync function scroll_into_view(el, enable = true) {\\n    if (window.__gradio_mode__ === \\"website\\" || window.__gradio_mode__ !== \\"app\\" && enable !== true) {\\n        return;\\n    }\\n    items.push(el);\\n    if (!called)\\n        called = true;\\n    else\\n        return;\\n    await tick();\\n    raf(() => {\\n        let min = [0, 0];\\n        for (let i = 0; i < items.length; i++) {\\n            const element = items[i];\\n            const box = element.getBoundingClientRect();\\n            if (i === 0 || box.top + window.scrollY <= min[0]) {\\n                min[0] = box.top + window.scrollY;\\n                min[1] = i;\\n            }\\n        }\\n        window.scrollTo({ top: min[0] - 20, behavior: \\"smooth\\" });\\n        called = false;\\n        items = [];\\n    });\\n}\\n<\/script>\\n\\n<script lang=\\"ts\\">import { onDestroy } from \\"svelte\\";\\nimport Loader from \\"./Loader.svelte\\";\\nimport { createEventDispatcher } from \\"svelte\\";\\nimport { IconButton } from \\"@gradio/atoms\\";\\nimport { Clear } from \\"@gradio/icons\\";\\nconst dispatch = createEventDispatcher();\\nexport let i18n;\\nexport let eta = null;\\nexport let queue_position;\\nexport let queue_size;\\nexport let status;\\nexport let scroll_to_output = false;\\nexport let timer = true;\\nexport let show_progress = \\"full\\";\\nexport let message = null;\\nexport let progress = null;\\nexport let variant = \\"default\\";\\nexport let loading_text = \\"Loading...\\";\\nexport let absolute = true;\\nexport let translucent = false;\\nexport let border = false;\\nexport let autoscroll;\\nlet el;\\nlet _timer = false;\\nlet timer_start = 0;\\nlet timer_diff = 0;\\nlet old_eta = null;\\nlet eta_from_start = null;\\nlet message_visible = false;\\nlet eta_level = 0;\\nlet progress_level = null;\\nlet last_progress_level = void 0;\\nlet progress_bar = null;\\nlet show_eta_bar = true;\\n$: eta_level = eta_from_start === null || eta_from_start <= 0 || !timer_diff ? null : Math.min(timer_diff / eta_from_start, 1);\\n$: if (progress != null) {\\n    show_eta_bar = false;\\n}\\n$: {\\n    if (progress != null) {\\n        progress_level = progress.map((p) => {\\n            if (p.index != null && p.length != null) {\\n                return p.index / p.length;\\n            }\\n            else if (p.progress != null) {\\n                return p.progress;\\n            }\\n            return void 0;\\n        });\\n    }\\n    else {\\n        progress_level = null;\\n    }\\n    if (progress_level) {\\n        last_progress_level = progress_level[progress_level.length - 1];\\n        if (progress_bar) {\\n            if (last_progress_level === 0) {\\n                progress_bar.style.transition = \\"0\\";\\n            }\\n            else {\\n                progress_bar.style.transition = \\"150ms\\";\\n            }\\n        }\\n    }\\n    else {\\n        last_progress_level = void 0;\\n    }\\n}\\nconst start_timer = () => {\\n    eta = old_eta = formatted_eta = null;\\n    timer_start = performance.now();\\n    timer_diff = 0;\\n    _timer = true;\\n    run();\\n};\\nfunction run() {\\n    raf(() => {\\n        timer_diff = (performance.now() - timer_start) / 1e3;\\n        if (_timer)\\n            run();\\n    });\\n}\\nfunction stop_timer() {\\n    timer_diff = 0;\\n    eta = old_eta = formatted_eta = null;\\n    if (!_timer)\\n        return;\\n    _timer = false;\\n}\\nonDestroy(() => {\\n    if (_timer)\\n        stop_timer();\\n});\\n$: {\\n    if (status === \\"pending\\") {\\n        start_timer();\\n    }\\n    else {\\n        stop_timer();\\n    }\\n}\\n$: el && scroll_to_output && (status === \\"pending\\" || status === \\"complete\\") && scroll_into_view(el, autoscroll);\\nlet formatted_eta = null;\\n$: {\\n    if (eta === null) {\\n        eta = old_eta;\\n    }\\n    if (eta != null && old_eta !== eta) {\\n        eta_from_start = (performance.now() - timer_start) / 1e3 + eta;\\n        formatted_eta = eta_from_start.toFixed(1);\\n        old_eta = eta;\\n    }\\n}\\nlet show_message_timeout = null;\\nfunction close_message() {\\n    message_visible = false;\\n    if (show_message_timeout !== null) {\\n        clearTimeout(show_message_timeout);\\n    }\\n}\\n$: {\\n    close_message();\\n    if (status === \\"error\\" && message) {\\n        message_visible = true;\\n    }\\n}\\n$: formatted_timer = timer_diff.toFixed(1);\\n<\/script>\\n\\n<div\\n\\tclass=\\"wrap {variant} {show_progress}\\"\\n\\tclass:hide={!status ||\\n\\t\\tstatus === \\"complete\\" ||\\n\\t\\tshow_progress === \\"hidden\\" ||\\n\\t\\tstatus == \\"streaming\\"}\\n\\tclass:translucent={(variant === \\"center\\" &&\\n\\t\\t(status === \\"pending\\" || status === \\"error\\")) ||\\n\\t\\ttranslucent ||\\n\\t\\tshow_progress === \\"minimal\\"}\\n\\tclass:generating={status === \\"generating\\" && show_progress === \\"full\\"}\\n\\tclass:border\\n\\tstyle:position={absolute ? \\"absolute\\" : \\"static\\"}\\n\\tstyle:padding={absolute ? \\"0\\" : \\"var(--size-8) 0\\"}\\n\\tbind:this={el}\\n>\\n\\t{#if status === \\"pending\\"}\\n\\t\\t{#if variant === \\"default\\" && show_eta_bar && show_progress === \\"full\\"}\\n\\t\\t\\t<div\\n\\t\\t\\t\\tclass=\\"eta-bar\\"\\n\\t\\t\\t\\tstyle:transform=\\"translateX({(eta_level || 0) * 100 - 100}%)\\"\\n\\t\\t\\t/>\\n\\t\\t{/if}\\n\\t\\t<div\\n\\t\\t\\tclass:meta-text-center={variant === \\"center\\"}\\n\\t\\t\\tclass:meta-text={variant === \\"default\\"}\\n\\t\\t\\tclass=\\"progress-text\\"\\n\\t\\t>\\n\\t\\t\\t{#if progress}\\n\\t\\t\\t\\t{#each progress as p}\\n\\t\\t\\t\\t\\t{#if p.index != null}\\n\\t\\t\\t\\t\\t\\t{#if p.length != null}\\n\\t\\t\\t\\t\\t\\t\\t{pretty_si(p.index || 0)}/{pretty_si(p.length)}\\n\\t\\t\\t\\t\\t\\t{:else}\\n\\t\\t\\t\\t\\t\\t\\t{pretty_si(p.index || 0)}\\n\\t\\t\\t\\t\\t\\t{/if}\\n\\t\\t\\t\\t\\t\\t{p.unit} | {\\" \\"}\\n\\t\\t\\t\\t\\t{/if}\\n\\t\\t\\t\\t{/each}\\n\\t\\t\\t{:else if queue_position !== null && queue_size !== undefined && queue_position >= 0}\\n\\t\\t\\t\\tqueue: {queue_position + 1}/{queue_size} |\\n\\t\\t\\t{:else if queue_position === 0}\\n\\t\\t\\t\\tprocessing |\\n\\t\\t\\t{/if}\\n\\n\\t\\t\\t{#if timer}\\n\\t\\t\\t\\t{formatted_timer}{eta ? `/${formatted_eta}` : \\"\\"}s\\n\\t\\t\\t{/if}\\n\\t\\t</div>\\n\\n\\t\\t{#if last_progress_level != null}\\n\\t\\t\\t<div class=\\"progress-level\\">\\n\\t\\t\\t\\t<div class=\\"progress-level-inner\\">\\n\\t\\t\\t\\t\\t{#if progress != null}\\n\\t\\t\\t\\t\\t\\t{#each progress as p, i}\\n\\t\\t\\t\\t\\t\\t\\t{#if p.desc != null || (progress_level && progress_level[i] != null)}\\n\\t\\t\\t\\t\\t\\t\\t\\t{#if i !== 0}\\n\\t\\t\\t\\t\\t\\t\\t\\t\\t&nbsp;/\\n\\t\\t\\t\\t\\t\\t\\t\\t{/if}\\n\\t\\t\\t\\t\\t\\t\\t\\t{#if p.desc != null}\\n\\t\\t\\t\\t\\t\\t\\t\\t\\t{p.desc}\\n\\t\\t\\t\\t\\t\\t\\t\\t{/if}\\n\\t\\t\\t\\t\\t\\t\\t\\t{#if p.desc != null && progress_level && progress_level[i] != null}\\n\\t\\t\\t\\t\\t\\t\\t\\t\\t-\\n\\t\\t\\t\\t\\t\\t\\t\\t{/if}\\n\\t\\t\\t\\t\\t\\t\\t\\t{#if progress_level != null}\\n\\t\\t\\t\\t\\t\\t\\t\\t\\t{(100 * (progress_level[i] || 0)).toFixed(1)}%\\n\\t\\t\\t\\t\\t\\t\\t\\t{/if}\\n\\t\\t\\t\\t\\t\\t\\t{/if}\\n\\t\\t\\t\\t\\t\\t{/each}\\n\\t\\t\\t\\t\\t{/if}\\n\\t\\t\\t\\t</div>\\n\\n\\t\\t\\t\\t<div class=\\"progress-bar-wrap\\">\\n\\t\\t\\t\\t\\t<div\\n\\t\\t\\t\\t\\t\\tbind:this={progress_bar}\\n\\t\\t\\t\\t\\t\\tclass=\\"progress-bar\\"\\n\\t\\t\\t\\t\\t\\tstyle:width=\\"{last_progress_level * 100}%\\"\\n\\t\\t\\t\\t\\t/>\\n\\t\\t\\t\\t</div>\\n\\t\\t\\t</div>\\n\\t\\t{:else if show_progress === \\"full\\"}\\n\\t\\t\\t<Loader margin={variant === \\"default\\"} />\\n\\t\\t{/if}\\n\\n\\t\\t{#if !timer}\\n\\t\\t\\t<p class=\\"loading\\">{loading_text}</p>\\n\\t\\t\\t<slot name=\\"additional-loading-text\\" />\\n\\t\\t{/if}\\n\\t{:else if status === \\"error\\"}\\n\\t\\t<div class=\\"clear-status\\">\\n\\t\\t\\t<IconButton\\n\\t\\t\\t\\tIcon={Clear}\\n\\t\\t\\t\\tlabel={i18n(\\"common.clear\\")}\\n\\t\\t\\t\\tdisabled={false}\\n\\t\\t\\t\\ton:click={() => {\\n\\t\\t\\t\\t\\tdispatch(\\"clear_status\\");\\n\\t\\t\\t\\t}}\\n\\t\\t\\t/>\\n\\t\\t</div>\\n\\t\\t<span class=\\"error\\">{i18n(\\"common.error\\")}</span>\\n\\t\\t<slot name=\\"error\\" />\\n\\t{/if}\\n</div>\\n\\n<style>\\n\\t.wrap {\\n\\t\\tdisplay: flex;\\n\\t\\tflex-direction: column;\\n\\t\\tjustify-content: center;\\n\\t\\talign-items: center;\\n\\t\\tz-index: var(--layer-2);\\n\\t\\ttransition: opacity 0.1s ease-in-out;\\n\\t\\tborder-radius: var(--block-radius);\\n\\t\\tbackground: var(--block-background-fill);\\n\\t\\tpadding: 0 var(--size-6);\\n\\t\\tmax-height: var(--size-screen-h);\\n\\t\\toverflow: hidden;\\n\\t}\\n\\n\\t.wrap.center {\\n\\t\\ttop: 0;\\n\\t\\tright: 0px;\\n\\t\\tleft: 0px;\\n\\t}\\n\\n\\t.wrap.default {\\n\\t\\ttop: 0px;\\n\\t\\tright: 0px;\\n\\t\\tbottom: 0px;\\n\\t\\tleft: 0px;\\n\\t}\\n\\n\\t.hide {\\n\\t\\topacity: 0;\\n\\t\\tpointer-events: none;\\n\\t}\\n\\n\\t.generating {\\n\\t\\tanimation:\\n\\t\\t\\tpulseStart 1s cubic-bezier(0.4, 0, 0.6, 1),\\n\\t\\t\\tpulse 2s cubic-bezier(0.4, 0, 0.6, 1) 1s infinite;\\n\\t\\tborder: 2px solid var(--color-accent);\\n\\t\\tbackground: transparent;\\n\\t\\tz-index: var(--layer-1);\\n\\t\\tpointer-events: none;\\n\\t}\\n\\n\\t.translucent {\\n\\t\\tbackground: none;\\n\\t}\\n\\n\\t@keyframes pulseStart {\\n\\t\\t0% {\\n\\t\\t\\topacity: 0;\\n\\t\\t}\\n\\t\\t100% {\\n\\t\\t\\topacity: 1;\\n\\t\\t}\\n\\t}\\n\\n\\t@keyframes pulse {\\n\\t\\t0%,\\n\\t\\t100% {\\n\\t\\t\\topacity: 1;\\n\\t\\t}\\n\\t\\t50% {\\n\\t\\t\\topacity: 0.5;\\n\\t\\t}\\n\\t}\\n\\n\\t.loading {\\n\\t\\tz-index: var(--layer-2);\\n\\t\\tcolor: var(--body-text-color);\\n\\t}\\n\\t.eta-bar {\\n\\t\\tposition: absolute;\\n\\t\\ttop: 0;\\n\\t\\tright: 0;\\n\\t\\tbottom: 0;\\n\\t\\tleft: 0;\\n\\t\\ttransform-origin: left;\\n\\t\\topacity: 0.8;\\n\\t\\tz-index: var(--layer-1);\\n\\t\\ttransition: 10ms;\\n\\t\\tbackground: var(--background-fill-secondary);\\n\\t}\\n\\t.progress-bar-wrap {\\n\\t\\tborder: 1px solid var(--border-color-primary);\\n\\t\\tbackground: var(--background-fill-primary);\\n\\t\\twidth: 55.5%;\\n\\t\\theight: var(--size-4);\\n\\t}\\n\\t.progress-bar {\\n\\t\\ttransform-origin: left;\\n\\t\\tbackground-color: var(--loader-color);\\n\\t\\twidth: var(--size-full);\\n\\t\\theight: var(--size-full);\\n\\t}\\n\\n\\t.progress-level {\\n\\t\\tdisplay: flex;\\n\\t\\tflex-direction: column;\\n\\t\\talign-items: center;\\n\\t\\tgap: 1;\\n\\t\\tz-index: var(--layer-2);\\n\\t\\twidth: var(--size-full);\\n\\t}\\n\\n\\t.progress-level-inner {\\n\\t\\tmargin: var(--size-2) auto;\\n\\t\\tcolor: var(--body-text-color);\\n\\t\\tfont-size: var(--text-sm);\\n\\t\\tfont-family: var(--font-mono);\\n\\t}\\n\\n\\t.meta-text {\\n\\t\\tposition: absolute;\\n\\t\\tbottom: 0;\\n\\t\\tright: 0;\\n\\t\\tz-index: var(--layer-2);\\n\\t\\tpadding: var(--size-1) var(--size-2);\\n\\t\\tfont-size: var(--text-sm);\\n\\t\\tfont-family: var(--font-mono);\\n\\t}\\n\\n\\t.meta-text-center {\\n\\t\\tdisplay: flex;\\n\\t\\tposition: absolute;\\n\\t\\ttop: 0;\\n\\t\\tright: 0;\\n\\t\\tjustify-content: center;\\n\\t\\talign-items: center;\\n\\t\\ttransform: translateY(var(--size-6));\\n\\t\\tz-index: var(--layer-2);\\n\\t\\tpadding: var(--size-1) var(--size-2);\\n\\t\\tfont-size: var(--text-sm);\\n\\t\\tfont-family: var(--font-mono);\\n\\t\\ttext-align: center;\\n\\t}\\n\\n\\t.error {\\n\\t\\tbox-shadow: var(--shadow-drop);\\n\\t\\tborder: solid 1px var(--error-border-color);\\n\\t\\tborder-radius: var(--radius-full);\\n\\t\\tbackground: var(--error-background-fill);\\n\\t\\tpadding-right: var(--size-4);\\n\\t\\tpadding-left: var(--size-4);\\n\\t\\tcolor: var(--error-text-color);\\n\\t\\tfont-weight: var(--weight-semibold);\\n\\t\\tfont-size: var(--text-lg);\\n\\t\\tline-height: var(--line-lg);\\n\\t\\tfont-family: var(--font);\\n\\t}\\n\\n\\t.minimal {\\n\\t\\tpointer-events: none;\\n\\t}\\n\\n\\t.minimal .progress-text {\\n\\t\\tbackground: var(--block-background-fill);\\n\\t}\\n\\n\\t.border {\\n\\t\\tborder: 1px solid var(--border-color-primary);\\n\\t}\\n\\n\\t.clear-status {\\n\\t\\tposition: absolute;\\n\\t\\tdisplay: flex;\\n\\t\\ttop: var(--size-2);\\n\\t\\tright: var(--size-2);\\n\\t\\tjustify-content: flex-end;\\n\\t\\tgap: var(--spacing-sm);\\n\\t\\tz-index: var(--layer-1);\\n\\t}</style>\\n"],"names":[],"mappings":"AA6QC,iCAAM,CACL,OAAO,CAAE,IAAI,CACb,cAAc,CAAE,MAAM,CACtB,eAAe,CAAE,MAAM,CACvB,WAAW,CAAE,MAAM,CACnB,OAAO,CAAE,IAAI,SAAS,CAAC,CACvB,UAAU,CAAE,OAAO,CAAC,IAAI,CAAC,WAAW,CACpC,aAAa,CAAE,IAAI,cAAc,CAAC,CAClC,UAAU,CAAE,IAAI,uBAAuB,CAAC,CACxC,OAAO,CAAE,CAAC,CAAC,IAAI,QAAQ,CAAC,CACxB,UAAU,CAAE,IAAI,eAAe,CAAC,CAChC,QAAQ,CAAE,MACX,CAEA,KAAK,mCAAQ,CACZ,GAAG,CAAE,CAAC,CACN,KAAK,CAAE,GAAG,CACV,IAAI,CAAE,GACP,CAEA,KAAK,oCAAS,CACb,GAAG,CAAE,GAAG,CACR,KAAK,CAAE,GAAG,CACV,MAAM,CAAE,GAAG,CACX,IAAI,CAAE,GACP,CAEA,iCAAM,CACL,OAAO,CAAE,CAAC,CACV,cAAc,CAAE,IACjB,CAEA,uCAAY,CACX,SAAS,CACR,wBAAU,CAAC,EAAE,CAAC,aAAa,GAAG,CAAC,CAAC,CAAC,CAAC,CAAC,GAAG,CAAC,CAAC,CAAC,CAAC;AAC7C,GAAG,mBAAK,CAAC,EAAE,CAAC,aAAa,GAAG,CAAC,CAAC,CAAC,CAAC,CAAC,GAAG,CAAC,CAAC,CAAC,CAAC,CAAC,EAAE,CAAC,QAAQ,CAClD,MAAM,CAAE,GAAG,CAAC,KAAK,CAAC,IAAI,cAAc,CAAC,CACrC,UAAU,CAAE,WAAW,CACvB,OAAO,CAAE,IAAI,SAAS,CAAC,CACvB,cAAc,CAAE,IACjB,CAEA,wCAAa,CACZ,UAAU,CAAE,IACb,CAEA,WAAW,wBAAW,CACrB,EAAG,CACF,OAAO,CAAE,CACV,CACA,IAAK,CACJ,OAAO,CAAE,CACV,CACD,CAEA,WAAW,mBAAM,CAChB,EAAE,CACF,IAAK,CACJ,OAAO,CAAE,CACV,CACA,GAAI,CACH,OAAO,CAAE,GACV,CACD,CAEA,oCAAS,CACR,OAAO,CAAE,IAAI,SAAS,CAAC,CACvB,KAAK,CAAE,IAAI,iBAAiB,CAC7B,CACA,oCAAS,CACR,QAAQ,CAAE,QAAQ,CAClB,GAAG,CAAE,CAAC,CACN,KAAK,CAAE,CAAC,CACR,MAAM,CAAE,CAAC,CACT,IAAI,CAAE,CAAC,CACP,gBAAgB,CAAE,IAAI,CACtB,OAAO,CAAE,GAAG,CACZ,OAAO,CAAE,IAAI,SAAS,CAAC,CACvB,UAAU,CAAE,IAAI,CAChB,UAAU,CAAE,IAAI,2BAA2B,CAC5C,CACA,8CAAmB,CAClB,MAAM,CAAE,GAAG,CAAC,KAAK,CAAC,IAAI,sBAAsB,CAAC,CAC7C,UAAU,CAAE,IAAI,yBAAyB,CAAC,CAC1C,KAAK,CAAE,KAAK,CACZ,MAAM,CAAE,IAAI,QAAQ,CACrB,CACA,yCAAc,CACb,gBAAgB,CAAE,IAAI,CACtB,gBAAgB,CAAE,IAAI,cAAc,CAAC,CACrC,KAAK,CAAE,IAAI,WAAW,CAAC,CACvB,MAAM,CAAE,IAAI,WAAW,CACxB,CAEA,2CAAgB,CACf,OAAO,CAAE,IAAI,CACb,cAAc,CAAE,MAAM,CACtB,WAAW,CAAE,MAAM,CACnB,GAAG,CAAE,CAAC,CACN,OAAO,CAAE,IAAI,SAAS,CAAC,CACvB,KAAK,CAAE,IAAI,WAAW,CACvB,CAEA,iDAAsB,CACrB,MAAM,CAAE,IAAI,QAAQ,CAAC,CAAC,IAAI,CAC1B,KAAK,CAAE,IAAI,iBAAiB,CAAC,CAC7B,SAAS,CAAE,IAAI,SAAS,CAAC,CACzB,WAAW,CAAE,IAAI,WAAW,CAC7B,CAEA,sCAAW,CACV,QAAQ,CAAE,QAAQ,CAClB,MAAM,CAAE,CAAC,CACT,KAAK,CAAE,CAAC,CACR,OAAO,CAAE,IAAI,SAAS,CAAC,CACvB,OAAO,CAAE,IAAI,QAAQ,CAAC,CAAC,IAAI,QAAQ,CAAC,CACpC,SAAS,CAAE,IAAI,SAAS,CAAC,CACzB,WAAW,CAAE,IAAI,WAAW,CAC7B,CAEA,6CAAkB,CACjB,OAAO,CAAE,IAAI,CACb,QAAQ,CAAE,QAAQ,CAClB,GAAG,CAAE,CAAC,CACN,KAAK,CAAE,CAAC,CACR,eAAe,CAAE,MAAM,CACvB,WAAW,CAAE,MAAM,CACnB,SAAS,CAAE,WAAW,IAAI,QAAQ,CAAC,CAAC,CACpC,OAAO,CAAE,IAAI,SAAS,CAAC,CACvB,OAAO,CAAE,IAAI,QAAQ,CAAC,CAAC,IAAI,QAAQ,CAAC,CACpC,SAAS,CAAE,IAAI,SAAS,CAAC,CACzB,WAAW,CAAE,IAAI,WAAW,CAAC,CAC7B,UAAU,CAAE,MACb,CAEA,kCAAO,CACN,UAAU,CAAE,IAAI,aAAa,CAAC,CAC9B,MAAM,CAAE,KAAK,CAAC,GAAG,CAAC,IAAI,oBAAoB,CAAC,CAC3C,aAAa,CAAE,IAAI,aAAa,CAAC,CACjC,UAAU,CAAE,IAAI,uBAAuB,CAAC,CACxC,aAAa,CAAE,IAAI,QAAQ,CAAC,CAC5B,YAAY,CAAE,IAAI,QAAQ,CAAC,CAC3B,KAAK,CAAE,IAAI,kBAAkB,CAAC,CAC9B,WAAW,CAAE,IAAI,iBAAiB,CAAC,CACnC,SAAS,CAAE,IAAI,SAAS,CAAC,CACzB,WAAW,CAAE,IAAI,SAAS,CAAC,CAC3B,WAAW,CAAE,IAAI,MAAM,CACxB,CAEA,oCAAS,CACR,cAAc,CAAE,IACjB,CAEA,sBAAQ,CAAC,4BAAe,CACvB,UAAU,CAAE,IAAI,uBAAuB,CACxC,CAEA,mCAAQ,CACP,MAAM,CAAE,GAAG,CAAC,KAAK,CAAC,IAAI,sBAAsB,CAC7C,CAEA,yCAAc,CACb,QAAQ,CAAE,QAAQ,CAClB,OAAO,CAAE,IAAI,CACb,GAAG,CAAE,IAAI,QAAQ,CAAC,CAClB,KAAK,CAAE,IAAI,QAAQ,CAAC,CACpB,eAAe,CAAE,QAAQ,CACzB,GAAG,CAAE,IAAI,YAAY,CAAC,CACtB,OAAO,CAAE,IAAI,SAAS,CACvB"}'},lt$1=typeof window<"u",at=lt$1?window.requestAnimationFrame:e=>{},Et=create_ssr_component((e,A,t,m)=>{let a;createEventDispatcher();let{i18n:c}=A,{eta:l=null}=A,{queue_position:i}=A,{queue_size:r}=A,{status:o}=A,{scroll_to_output:s=!1}=A,{timer:u=!0}=A,{show_progress:d="full"}=A,{message:p=null}=A,{progress:g=null}=A,{variant:v="default"}=A,{loading_text:z="Loading..."}=A,{absolute:w=!0}=A,{translucent:k=!1}=A,{border:Q=!1}=A,{autoscroll:j$1}=A,P,E=!1,W=0,I=0,y=null,b=null,U=0,f=null,_,X=null,Y=!0;const D=()=>{l=y=K=null,W=performance.now(),I=0,E=!0,F();};function F(){at(()=>{I=(performance.now()-W)/1e3,E&&F();});}function L(){I=0,l=y=K=null,E&&(E=!1);}onDestroy(()=>{E&&L();});let K=null;return A.i18n===void 0&&t.i18n&&c!==void 0&&t.i18n(c),A.eta===void 0&&t.eta&&l!==void 0&&t.eta(l),A.queue_position===void 0&&t.queue_position&&i!==void 0&&t.queue_position(i),A.queue_size===void 0&&t.queue_size&&r!==void 0&&t.queue_size(r),A.status===void 0&&t.status&&o!==void 0&&t.status(o),A.scroll_to_output===void 0&&t.scroll_to_output&&s!==void 0&&t.scroll_to_output(s),A.timer===void 0&&t.timer&&u!==void 0&&t.timer(u),A.show_progress===void 0&&t.show_progress&&d!==void 0&&t.show_progress(d),A.message===void 0&&t.message&&p!==void 0&&t.message(p),A.progress===void 0&&t.progress&&g!==void 0&&t.progress(g),A.variant===void 0&&t.variant&&v!==void 0&&t.variant(v),A.loading_text===void 0&&t.loading_text&&z!==void 0&&t.loading_text(z),A.absolute===void 0&&t.absolute&&w!==void 0&&t.absolute(w),A.translucent===void 0&&t.translucent&&k!==void 0&&t.translucent(k),A.border===void 0&&t.border&&Q!==void 0&&t.border(Q),A.autoscroll===void 0&&t.autoscroll&&j$1!==void 0&&t.autoscroll(j$1),e.css.add(ot),l===null&&(l=y),l!=null&&y!==l&&(b=(performance.now()-W)/1e3+l,K=b.toFixed(1),y=l),U=b===null||b<=0||!I?null:Math.min(I/b,1),g!=null&&(Y=!1),g!=null?f=g.map(C=>{if(C.index!=null&&C.length!=null)return C.index/C.length;if(C.progress!=null)return C.progress}):f=null,f?_=f[f.length-1]:_=void 0,o==="pending"?D():L(),a=I.toFixed(1),`<div class="${["wrap "+escape(v,!0)+" "+escape(d,!0)+" svelte-ls20lj",(!o||o==="complete"||d==="hidden"||o=="streaming"?"hide":"")+" "+(v==="center"&&(o==="pending"||o==="error")||k||d==="minimal"?"translucent":"")+" "+(o==="generating"&&d==="full"?"generating":"")+" "+(Q?"border":"")].join(" ").trim()}"${add_styles({position:w?"absolute":"static",padding:w?"0":"var(--size-8) 0"})}${add_attribute("this",P,0)}>${o==="pending"?`${v==="default"&&Y&&d==="full"?`<div class="eta-bar svelte-ls20lj"${add_styles({transform:`translateX(${(U||0)*100-100}%)`})}></div>`:""} <div class="${["progress-text svelte-ls20lj",(v==="center"?"meta-text-center":"")+" "+(v==="default"?"meta-text":"")].join(" ").trim()}">${g?`${each(g,C=>`${C.index!=null?`${C.length!=null?`${escape(S(C.index||0))}/${escape(S(C.length))}`:`${escape(S(C.index||0))}`} ${escape(C.unit)} | ${escape(" ")}`:""}`)}`:`${i!==null&&r!==void 0&&i>=0?`queue: ${escape(i+1)}/${escape(r)} |`:`${i===0?"processing |":""}`}`} ${u?`${escape(a)}${escape(l?`/${K}`:"")}s`:""}</div> ${_!=null?`<div class="progress-level svelte-ls20lj"><div class="progress-level-inner svelte-ls20lj">${g!=null?`${each(g,(C,M)=>`${C.desc!=null||f&&f[M]!=null?`${M!==0?" /":""} ${C.desc!=null?`${escape(C.desc)}`:""} ${C.desc!=null&&f&&f[M]!=null?"-":""} ${f!=null?`${escape((100*(f[M]||0)).toFixed(1))}%`:""}`:""}`)}`:""}</div> <div class="progress-bar-wrap svelte-ls20lj"><div class="progress-bar svelte-ls20lj"${add_styles({width:`${_*100}%`})}${add_attribute("this",X,0)}></div></div></div>`:`${d==="full"?`${validate_component(rt,"Loader").$$render(e,{margin:v==="default"},{},{})}`:""}`} ${u?"":`<p class="loading svelte-ls20lj">${escape(z)}</p> ${m["additional-loading-text"]?m["additional-loading-text"]({}):""}`}`:`${o==="error"?`<div class="clear-status svelte-ls20lj">${validate_component(j,"IconButton").$$render(e,{Icon:qt,label:c("common.clear"),disabled:!1},{},{})}</div> <span class="error svelte-ls20lj">${escape(c("common.error"))}</span> ${m.error?m.error({}):""}`:""}`} </div>`});function st(e){return dn$1(e)}const Ct={code:".toast-body.svelte-fee5uc{display:flex;position:relative;right:0;left:0;align-items:center;margin:var(--size-6) var(--size-4);margin:auto;border-radius:var(--container-radius);overflow:hidden;pointer-events:auto}.toast-body.error.svelte-fee5uc{border:1px solid var(--color-red-700);background:var(--color-red-50)}.dark .toast-body.error.svelte-fee5uc{border:1px solid var(--color-red-500);background-color:var(--color-grey-950)}.toast-body.warning.svelte-fee5uc{border:1px solid var(--color-yellow-700);background:var(--color-yellow-50)}.dark .toast-body.warning.svelte-fee5uc{border:1px solid var(--color-yellow-500);background-color:var(--color-grey-950)}.toast-body.info.svelte-fee5uc{border:1px solid var(--color-grey-700);background:var(--color-grey-50)}.dark .toast-body.info.svelte-fee5uc{border:1px solid var(--color-grey-500);background-color:var(--color-grey-950)}.toast-body.success.svelte-fee5uc{border:1px solid var(--color-green-700);background:var(--color-green-50)}.dark .toast-body.success.svelte-fee5uc{border:1px solid var(--color-green-500);background-color:var(--color-grey-950)}.toast-title.svelte-fee5uc{display:flex;align-items:center;font-weight:var(--weight-bold);font-size:var(--text-lg);line-height:var(--line-sm)}.toast-title.error.svelte-fee5uc{color:var(--color-red-700)}.dark .toast-title.error.svelte-fee5uc{color:var(--color-red-50)}.toast-title.warning.svelte-fee5uc{color:var(--color-yellow-700)}.dark .toast-title.warning.svelte-fee5uc{color:var(--color-yellow-50)}.toast-title.info.svelte-fee5uc{color:var(--color-grey-700)}.dark .toast-title.info.svelte-fee5uc{color:var(--color-grey-50)}.toast-title.success.svelte-fee5uc{color:var(--color-green-700)}.dark .toast-title.success.svelte-fee5uc{color:var(--color-green-50)}.toast-close.svelte-fee5uc{margin:0 var(--size-3);border-radius:var(--size-3);padding:0px var(--size-1-5);font-size:var(--size-5);line-height:var(--size-5)}.toast-close.error.svelte-fee5uc{color:var(--color-red-700)}.dark .toast-close.error.svelte-fee5uc{color:var(--color-red-500)}.toast-close.warning.svelte-fee5uc{color:var(--color-yellow-700)}.dark .toast-close.warning.svelte-fee5uc{color:var(--color-yellow-500)}.toast-close.info.svelte-fee5uc{color:var(--color-grey-700)}.dark .toast-close.info.svelte-fee5uc{color:var(--color-grey-500)}.toast-close.success.svelte-fee5uc{color:var(--color-green-700)}.dark .toast-close.success.svelte-fee5uc{color:var(--color-green-500)}.toast-text.svelte-fee5uc{font-size:var(--text-lg);word-wrap:break-word;overflow-wrap:break-word;word-break:break-word}.toast-text.error.svelte-fee5uc{color:var(--color-red-700)}.dark .toast-text.error.svelte-fee5uc{color:var(--color-red-50)}.toast-text.warning.svelte-fee5uc{color:var(--color-yellow-700)}.dark .toast-text.warning.svelte-fee5uc{color:var(--color-yellow-50)}.toast-text.info.svelte-fee5uc{color:var(--color-grey-700)}.dark .toast-text.info.svelte-fee5uc{color:var(--color-grey-50)}.toast-text.success.svelte-fee5uc{color:var(--color-green-700)}.dark .toast-text.success.svelte-fee5uc{color:var(--color-green-50)}.toast-details.svelte-fee5uc{margin:var(--size-3) var(--size-3) var(--size-3) 0;width:100%}.toast-icon.svelte-fee5uc{display:flex;position:absolute;position:relative;flex-shrink:0;justify-content:center;align-items:center;margin:var(--size-2);border-radius:var(--radius-full);padding:var(--size-1);padding-left:calc(var(--size-1) - 1px);width:35px;height:35px}.toast-icon.error.svelte-fee5uc{color:var(--color-red-700)}.dark .toast-icon.error.svelte-fee5uc{color:var(--color-red-500)}.toast-icon.warning.svelte-fee5uc{color:var(--color-yellow-700)}.dark .toast-icon.warning.svelte-fee5uc{color:var(--color-yellow-500)}.toast-icon.info.svelte-fee5uc{color:var(--color-grey-700)}.dark .toast-icon.info.svelte-fee5uc{color:var(--color-grey-500)}.toast-icon.success.svelte-fee5uc{color:var(--color-green-700)}.dark .toast-icon.success.svelte-fee5uc{color:var(--color-green-500)}@keyframes svelte-fee5uc-countdown{from{transform:scaleX(1)}to{transform:scaleX(0)}}.timer.svelte-fee5uc{position:absolute;bottom:0;left:0;transform-origin:0 0;animation:svelte-fee5uc-countdown 10s linear forwards;width:100%;height:var(--size-1)}.timer.error.svelte-fee5uc{background:var(--color-red-700)}.dark .timer.error.svelte-fee5uc{background:var(--color-red-500)}.timer.warning.svelte-fee5uc{background:var(--color-yellow-700)}.dark .timer.warning.svelte-fee5uc{background:var(--color-yellow-500)}.timer.info.svelte-fee5uc{background:var(--color-grey-700)}.dark .timer.info.svelte-fee5uc{background:var(--color-grey-500)}.timer.success.svelte-fee5uc{background:var(--color-green-700)}.dark .timer.success.svelte-fee5uc{background:var(--color-green-500)}.hidden.svelte-fee5uc{display:none}.toast-text.svelte-fee5uc a{text-decoration:underline}",map:'{"version":3,"file":"ToastContent.svelte","sources":["ToastContent.svelte"],"sourcesContent":["<script lang=\\"ts\\">import { Error, Info, Warning, Success } from \\"@gradio/icons\\";\\nimport { sanitize } from \\"@gradio/sanitize\\";\\nimport { createEventDispatcher, onMount } from \\"svelte\\";\\nimport { fade } from \\"svelte/transition\\";\\nexport let title = \\"\\";\\nexport let message = \\"\\";\\nexport let type;\\nexport let id;\\nexport let duration = 10;\\nexport let visible = true;\\n$: message = sanitize(message);\\n$: display = visible;\\n$: duration = duration || null;\\nconst dispatch = createEventDispatcher();\\nfunction close_message() {\\n    dispatch(\\"close\\", id);\\n}\\nonMount(() => {\\n    if (duration !== null) {\\n        setTimeout(() => {\\n            close_message();\\n        }, duration * 1e3);\\n    }\\n});\\n$: timer_animation_duration = `${duration || 0}s`;\\n<\/script>\\n\\n<!-- TODO: fix-->\\n<!-- svelte-ignore a11y-no-noninteractive-element-interactions-->\\n<div\\n\\tclass=\\"toast-body {type}\\"\\n\\trole=\\"alert\\"\\n\\tdata-testid=\\"toast-body\\"\\n\\tclass:hidden={!display}\\n\\ton:click|stopPropagation\\n\\ton:keydown|stopPropagation\\n\\tin:fade={{ duration: 200, delay: 100 }}\\n\\tout:fade={{ duration: 200 }}\\n>\\n\\t<div class=\\"toast-icon {type}\\">\\n\\t\\t{#if type === \\"warning\\"}\\n\\t\\t\\t<Warning />\\n\\t\\t{:else if type === \\"info\\"}\\n\\t\\t\\t<Info />\\n\\t\\t{:else if type === \\"success\\"}\\n\\t\\t\\t<Success />\\n\\t\\t{:else if type === \\"error\\"}\\n\\t\\t\\t<Error />\\n\\t\\t{/if}\\n\\t</div>\\n\\n\\t<div class=\\"toast-details {type}\\">\\n\\t\\t<div class=\\"toast-title {type}\\">{title}</div>\\n\\t\\t<div class=\\"toast-text {type}\\">\\n\\t\\t\\t{@html message}\\n\\t\\t</div>\\n\\t</div>\\n\\n\\t<button\\n\\t\\ton:click={close_message}\\n\\t\\tclass=\\"toast-close {type}\\"\\n\\t\\ttype=\\"button\\"\\n\\t\\taria-label=\\"Close\\"\\n\\t\\tdata-testid=\\"toast-close\\"\\n\\t>\\n\\t\\t<span aria-hidden=\\"true\\">&#215;</span>\\n\\t</button>\\n\\n\\t<div\\n\\t\\tclass=\\"timer {type}\\"\\n\\t\\tstyle={`animation-duration: ${timer_animation_duration};`}\\n\\t/>\\n</div>\\n\\n<style>\\n\\t.toast-body {\\n\\t\\tdisplay: flex;\\n\\t\\tposition: relative;\\n\\t\\tright: 0;\\n\\t\\tleft: 0;\\n\\t\\talign-items: center;\\n\\t\\tmargin: var(--size-6) var(--size-4);\\n\\t\\tmargin: auto;\\n\\t\\tborder-radius: var(--container-radius);\\n\\t\\toverflow: hidden;\\n\\t\\tpointer-events: auto;\\n\\t}\\n\\n\\t.toast-body.error {\\n\\t\\tborder: 1px solid var(--color-red-700);\\n\\t\\tbackground: var(--color-red-50);\\n\\t}\\n\\n\\t:global(.dark) .toast-body.error {\\n\\t\\tborder: 1px solid var(--color-red-500);\\n\\t\\tbackground-color: var(--color-grey-950);\\n\\t}\\n\\n\\t.toast-body.warning {\\n\\t\\tborder: 1px solid var(--color-yellow-700);\\n\\t\\tbackground: var(--color-yellow-50);\\n\\t}\\n\\t:global(.dark) .toast-body.warning {\\n\\t\\tborder: 1px solid var(--color-yellow-500);\\n\\t\\tbackground-color: var(--color-grey-950);\\n\\t}\\n\\n\\t.toast-body.info {\\n\\t\\tborder: 1px solid var(--color-grey-700);\\n\\t\\tbackground: var(--color-grey-50);\\n\\t}\\n\\t:global(.dark) .toast-body.info {\\n\\t\\tborder: 1px solid var(--color-grey-500);\\n\\t\\tbackground-color: var(--color-grey-950);\\n\\t}\\n\\n\\t.toast-body.success {\\n\\t\\tborder: 1px solid var(--color-green-700);\\n\\t\\tbackground: var(--color-green-50);\\n\\t}\\n\\t:global(.dark) .toast-body.success {\\n\\t\\tborder: 1px solid var(--color-green-500);\\n\\t\\tbackground-color: var(--color-grey-950);\\n\\t}\\n\\n\\t.toast-title {\\n\\t\\tdisplay: flex;\\n\\t\\talign-items: center;\\n\\t\\tfont-weight: var(--weight-bold);\\n\\t\\tfont-size: var(--text-lg);\\n\\t\\tline-height: var(--line-sm);\\n\\t}\\n\\n\\t.toast-title.error {\\n\\t\\tcolor: var(--color-red-700);\\n\\t}\\n\\t:global(.dark) .toast-title.error {\\n\\t\\tcolor: var(--color-red-50);\\n\\t}\\n\\n\\t.toast-title.warning {\\n\\t\\tcolor: var(--color-yellow-700);\\n\\t}\\n\\t:global(.dark) .toast-title.warning {\\n\\t\\tcolor: var(--color-yellow-50);\\n\\t}\\n\\n\\t.toast-title.info {\\n\\t\\tcolor: var(--color-grey-700);\\n\\t}\\n\\t:global(.dark) .toast-title.info {\\n\\t\\tcolor: var(--color-grey-50);\\n\\t}\\n\\n\\t.toast-title.success {\\n\\t\\tcolor: var(--color-green-700);\\n\\t}\\n\\t:global(.dark) .toast-title.success {\\n\\t\\tcolor: var(--color-green-50);\\n\\t}\\n\\n\\t.toast-close {\\n\\t\\tmargin: 0 var(--size-3);\\n\\t\\tborder-radius: var(--size-3);\\n\\t\\tpadding: 0px var(--size-1-5);\\n\\t\\tfont-size: var(--size-5);\\n\\t\\tline-height: var(--size-5);\\n\\t}\\n\\n\\t.toast-close.error {\\n\\t\\tcolor: var(--color-red-700);\\n\\t}\\n\\t:global(.dark) .toast-close.error {\\n\\t\\tcolor: var(--color-red-500);\\n\\t}\\n\\n\\t.toast-close.warning {\\n\\t\\tcolor: var(--color-yellow-700);\\n\\t}\\n\\t:global(.dark) .toast-close.warning {\\n\\t\\tcolor: var(--color-yellow-500);\\n\\t}\\n\\n\\t.toast-close.info {\\n\\t\\tcolor: var(--color-grey-700);\\n\\t}\\n\\t:global(.dark) .toast-close.info {\\n\\t\\tcolor: var(--color-grey-500);\\n\\t}\\n\\n\\t.toast-close.success {\\n\\t\\tcolor: var(--color-green-700);\\n\\t}\\n\\t:global(.dark) .toast-close.success {\\n\\t\\tcolor: var(--color-green-500);\\n\\t}\\n\\n\\t.toast-text {\\n\\t\\tfont-size: var(--text-lg);\\n\\t\\tword-wrap: break-word;\\n\\t\\toverflow-wrap: break-word;\\n\\t\\tword-break: break-word;\\n\\t}\\n\\n\\t.toast-text.error {\\n\\t\\tcolor: var(--color-red-700);\\n\\t}\\n\\t:global(.dark) .toast-text.error {\\n\\t\\tcolor: var(--color-red-50);\\n\\t}\\n\\n\\t.toast-text.warning {\\n\\t\\tcolor: var(--color-yellow-700);\\n\\t}\\n\\n\\t:global(.dark) .toast-text.warning {\\n\\t\\tcolor: var(--color-yellow-50);\\n\\t}\\n\\n\\t.toast-text.info {\\n\\t\\tcolor: var(--color-grey-700);\\n\\t}\\n\\n\\t:global(.dark) .toast-text.info {\\n\\t\\tcolor: var(--color-grey-50);\\n\\t}\\n\\n\\t.toast-text.success {\\n\\t\\tcolor: var(--color-green-700);\\n\\t}\\n\\t:global(.dark) .toast-text.success {\\n\\t\\tcolor: var(--color-green-50);\\n\\t}\\n\\n\\t.toast-details {\\n\\t\\tmargin: var(--size-3) var(--size-3) var(--size-3) 0;\\n\\t\\twidth: 100%;\\n\\t}\\n\\n\\t.toast-icon {\\n\\t\\tdisplay: flex;\\n\\t\\tposition: absolute;\\n\\t\\tposition: relative;\\n\\t\\tflex-shrink: 0;\\n\\t\\tjustify-content: center;\\n\\t\\talign-items: center;\\n\\t\\tmargin: var(--size-2);\\n\\t\\tborder-radius: var(--radius-full);\\n\\t\\tpadding: var(--size-1);\\n\\t\\tpadding-left: calc(var(--size-1) - 1px);\\n\\t\\twidth: 35px;\\n\\t\\theight: 35px;\\n\\t}\\n\\n\\t.toast-icon.error {\\n\\t\\tcolor: var(--color-red-700);\\n\\t}\\n\\n\\t:global(.dark) .toast-icon.error {\\n\\t\\tcolor: var(--color-red-500);\\n\\t}\\n\\n\\t.toast-icon.warning {\\n\\t\\tcolor: var(--color-yellow-700);\\n\\t}\\n\\n\\t:global(.dark) .toast-icon.warning {\\n\\t\\tcolor: var(--color-yellow-500);\\n\\t}\\n\\n\\t.toast-icon.info {\\n\\t\\tcolor: var(--color-grey-700);\\n\\t}\\n\\n\\t:global(.dark) .toast-icon.info {\\n\\t\\tcolor: var(--color-grey-500);\\n\\t}\\n\\n\\t.toast-icon.success {\\n\\t\\tcolor: var(--color-green-700);\\n\\t}\\n\\n\\t:global(.dark) .toast-icon.success {\\n\\t\\tcolor: var(--color-green-500);\\n\\t}\\n\\n\\t@keyframes countdown {\\n\\t\\tfrom {\\n\\t\\t\\ttransform: scaleX(1);\\n\\t\\t}\\n\\t\\tto {\\n\\t\\t\\ttransform: scaleX(0);\\n\\t\\t}\\n\\t}\\n\\n\\t.timer {\\n\\t\\tposition: absolute;\\n\\t\\tbottom: 0;\\n\\t\\tleft: 0;\\n\\t\\ttransform-origin: 0 0;\\n\\t\\tanimation: countdown 10s linear forwards;\\n\\t\\twidth: 100%;\\n\\t\\theight: var(--size-1);\\n\\t}\\n\\n\\t.timer.error {\\n\\t\\tbackground: var(--color-red-700);\\n\\t}\\n\\n\\t:global(.dark) .timer.error {\\n\\t\\tbackground: var(--color-red-500);\\n\\t}\\n\\n\\t.timer.warning {\\n\\t\\tbackground: var(--color-yellow-700);\\n\\t}\\n\\n\\t:global(.dark) .timer.warning {\\n\\t\\tbackground: var(--color-yellow-500);\\n\\t}\\n\\n\\t.timer.info {\\n\\t\\tbackground: var(--color-grey-700);\\n\\t}\\n\\n\\t:global(.dark) .timer.info {\\n\\t\\tbackground: var(--color-grey-500);\\n\\t}\\n\\n\\t.timer.success {\\n\\t\\tbackground: var(--color-green-700);\\n\\t}\\n\\n\\t:global(.dark) .timer.success {\\n\\t\\tbackground: var(--color-green-500);\\n\\t}\\n\\n\\t.hidden {\\n\\t\\tdisplay: none;\\n\\t}\\n\\n\\t.toast-text :global(a) {\\n\\t\\ttext-decoration: underline;\\n\\t}</style>\\n"],"names":[],"mappings":"AA2EC,yBAAY,CACX,OAAO,CAAE,IAAI,CACb,QAAQ,CAAE,QAAQ,CAClB,KAAK,CAAE,CAAC,CACR,IAAI,CAAE,CAAC,CACP,WAAW,CAAE,MAAM,CACnB,MAAM,CAAE,IAAI,QAAQ,CAAC,CAAC,IAAI,QAAQ,CAAC,CACnC,MAAM,CAAE,IAAI,CACZ,aAAa,CAAE,IAAI,kBAAkB,CAAC,CACtC,QAAQ,CAAE,MAAM,CAChB,cAAc,CAAE,IACjB,CAEA,WAAW,oBAAO,CACjB,MAAM,CAAE,GAAG,CAAC,KAAK,CAAC,IAAI,eAAe,CAAC,CACtC,UAAU,CAAE,IAAI,cAAc,CAC/B,CAEQ,KAAM,CAAC,WAAW,oBAAO,CAChC,MAAM,CAAE,GAAG,CAAC,KAAK,CAAC,IAAI,eAAe,CAAC,CACtC,gBAAgB,CAAE,IAAI,gBAAgB,CACvC,CAEA,WAAW,sBAAS,CACnB,MAAM,CAAE,GAAG,CAAC,KAAK,CAAC,IAAI,kBAAkB,CAAC,CACzC,UAAU,CAAE,IAAI,iBAAiB,CAClC,CACQ,KAAM,CAAC,WAAW,sBAAS,CAClC,MAAM,CAAE,GAAG,CAAC,KAAK,CAAC,IAAI,kBAAkB,CAAC,CACzC,gBAAgB,CAAE,IAAI,gBAAgB,CACvC,CAEA,WAAW,mBAAM,CAChB,MAAM,CAAE,GAAG,CAAC,KAAK,CAAC,IAAI,gBAAgB,CAAC,CACvC,UAAU,CAAE,IAAI,eAAe,CAChC,CACQ,KAAM,CAAC,WAAW,mBAAM,CAC/B,MAAM,CAAE,GAAG,CAAC,KAAK,CAAC,IAAI,gBAAgB,CAAC,CACvC,gBAAgB,CAAE,IAAI,gBAAgB,CACvC,CAEA,WAAW,sBAAS,CACnB,MAAM,CAAE,GAAG,CAAC,KAAK,CAAC,IAAI,iBAAiB,CAAC,CACxC,UAAU,CAAE,IAAI,gBAAgB,CACjC,CACQ,KAAM,CAAC,WAAW,sBAAS,CAClC,MAAM,CAAE,GAAG,CAAC,KAAK,CAAC,IAAI,iBAAiB,CAAC,CACxC,gBAAgB,CAAE,IAAI,gBAAgB,CACvC,CAEA,0BAAa,CACZ,OAAO,CAAE,IAAI,CACb,WAAW,CAAE,MAAM,CACnB,WAAW,CAAE,IAAI,aAAa,CAAC,CAC/B,SAAS,CAAE,IAAI,SAAS,CAAC,CACzB,WAAW,CAAE,IAAI,SAAS,CAC3B,CAEA,YAAY,oBAAO,CAClB,KAAK,CAAE,IAAI,eAAe,CAC3B,CACQ,KAAM,CAAC,YAAY,oBAAO,CACjC,KAAK,CAAE,IAAI,cAAc,CAC1B,CAEA,YAAY,sBAAS,CACpB,KAAK,CAAE,IAAI,kBAAkB,CAC9B,CACQ,KAAM,CAAC,YAAY,sBAAS,CACnC,KAAK,CAAE,IAAI,iBAAiB,CAC7B,CAEA,YAAY,mBAAM,CACjB,KAAK,CAAE,IAAI,gBAAgB,CAC5B,CACQ,KAAM,CAAC,YAAY,mBAAM,CAChC,KAAK,CAAE,IAAI,eAAe,CAC3B,CAEA,YAAY,sBAAS,CACpB,KAAK,CAAE,IAAI,iBAAiB,CAC7B,CACQ,KAAM,CAAC,YAAY,sBAAS,CACnC,KAAK,CAAE,IAAI,gBAAgB,CAC5B,CAEA,0BAAa,CACZ,MAAM,CAAE,CAAC,CAAC,IAAI,QAAQ,CAAC,CACvB,aAAa,CAAE,IAAI,QAAQ,CAAC,CAC5B,OAAO,CAAE,GAAG,CAAC,IAAI,UAAU,CAAC,CAC5B,SAAS,CAAE,IAAI,QAAQ,CAAC,CACxB,WAAW,CAAE,IAAI,QAAQ,CAC1B,CAEA,YAAY,oBAAO,CAClB,KAAK,CAAE,IAAI,eAAe,CAC3B,CACQ,KAAM,CAAC,YAAY,oBAAO,CACjC,KAAK,CAAE,IAAI,eAAe,CAC3B,CAEA,YAAY,sBAAS,CACpB,KAAK,CAAE,IAAI,kBAAkB,CAC9B,CACQ,KAAM,CAAC,YAAY,sBAAS,CACnC,KAAK,CAAE,IAAI,kBAAkB,CAC9B,CAEA,YAAY,mBAAM,CACjB,KAAK,CAAE,IAAI,gBAAgB,CAC5B,CACQ,KAAM,CAAC,YAAY,mBAAM,CAChC,KAAK,CAAE,IAAI,gBAAgB,CAC5B,CAEA,YAAY,sBAAS,CACpB,KAAK,CAAE,IAAI,iBAAiB,CAC7B,CACQ,KAAM,CAAC,YAAY,sBAAS,CACnC,KAAK,CAAE,IAAI,iBAAiB,CAC7B,CAEA,yBAAY,CACX,SAAS,CAAE,IAAI,SAAS,CAAC,CACzB,SAAS,CAAE,UAAU,CACrB,aAAa,CAAE,UAAU,CACzB,UAAU,CAAE,UACb,CAEA,WAAW,oBAAO,CACjB,KAAK,CAAE,IAAI,eAAe,CAC3B,CACQ,KAAM,CAAC,WAAW,oBAAO,CAChC,KAAK,CAAE,IAAI,cAAc,CAC1B,CAEA,WAAW,sBAAS,CACnB,KAAK,CAAE,IAAI,kBAAkB,CAC9B,CAEQ,KAAM,CAAC,WAAW,sBAAS,CAClC,KAAK,CAAE,IAAI,iBAAiB,CAC7B,CAEA,WAAW,mBAAM,CAChB,KAAK,CAAE,IAAI,gBAAgB,CAC5B,CAEQ,KAAM,CAAC,WAAW,mBAAM,CAC/B,KAAK,CAAE,IAAI,eAAe,CAC3B,CAEA,WAAW,sBAAS,CACnB,KAAK,CAAE,IAAI,iBAAiB,CAC7B,CACQ,KAAM,CAAC,WAAW,sBAAS,CAClC,KAAK,CAAE,IAAI,gBAAgB,CAC5B,CAEA,4BAAe,CACd,MAAM,CAAE,IAAI,QAAQ,CAAC,CAAC,IAAI,QAAQ,CAAC,CAAC,IAAI,QAAQ,CAAC,CAAC,CAAC,CACnD,KAAK,CAAE,IACR,CAEA,yBAAY,CACX,OAAO,CAAE,IAAI,CACb,QAAQ,CAAE,QAAQ,CAClB,QAAQ,CAAE,QAAQ,CAClB,WAAW,CAAE,CAAC,CACd,eAAe,CAAE,MAAM,CACvB,WAAW,CAAE,MAAM,CACnB,MAAM,CAAE,IAAI,QAAQ,CAAC,CACrB,aAAa,CAAE,IAAI,aAAa,CAAC,CACjC,OAAO,CAAE,IAAI,QAAQ,CAAC,CACtB,YAAY,CAAE,KAAK,IAAI,QAAQ,CAAC,CAAC,CAAC,CAAC,GAAG,CAAC,CACvC,KAAK,CAAE,IAAI,CACX,MAAM,CAAE,IACT,CAEA,WAAW,oBAAO,CACjB,KAAK,CAAE,IAAI,eAAe,CAC3B,CAEQ,KAAM,CAAC,WAAW,oBAAO,CAChC,KAAK,CAAE,IAAI,eAAe,CAC3B,CAEA,WAAW,sBAAS,CACnB,KAAK,CAAE,IAAI,kBAAkB,CAC9B,CAEQ,KAAM,CAAC,WAAW,sBAAS,CAClC,KAAK,CAAE,IAAI,kBAAkB,CAC9B,CAEA,WAAW,mBAAM,CAChB,KAAK,CAAE,IAAI,gBAAgB,CAC5B,CAEQ,KAAM,CAAC,WAAW,mBAAM,CAC/B,KAAK,CAAE,IAAI,gBAAgB,CAC5B,CAEA,WAAW,sBAAS,CACnB,KAAK,CAAE,IAAI,iBAAiB,CAC7B,CAEQ,KAAM,CAAC,WAAW,sBAAS,CAClC,KAAK,CAAE,IAAI,iBAAiB,CAC7B,CAEA,WAAW,uBAAU,CACpB,IAAK,CACJ,SAAS,CAAE,OAAO,CAAC,CACpB,CACA,EAAG,CACF,SAAS,CAAE,OAAO,CAAC,CACpB,CACD,CAEA,oBAAO,CACN,QAAQ,CAAE,QAAQ,CAClB,MAAM,CAAE,CAAC,CACT,IAAI,CAAE,CAAC,CACP,gBAAgB,CAAE,CAAC,CAAC,CAAC,CACrB,SAAS,CAAE,uBAAS,CAAC,GAAG,CAAC,MAAM,CAAC,QAAQ,CACxC,KAAK,CAAE,IAAI,CACX,MAAM,CAAE,IAAI,QAAQ,CACrB,CAEA,MAAM,oBAAO,CACZ,UAAU,CAAE,IAAI,eAAe,CAChC,CAEQ,KAAM,CAAC,MAAM,oBAAO,CAC3B,UAAU,CAAE,IAAI,eAAe,CAChC,CAEA,MAAM,sBAAS,CACd,UAAU,CAAE,IAAI,kBAAkB,CACnC,CAEQ,KAAM,CAAC,MAAM,sBAAS,CAC7B,UAAU,CAAE,IAAI,kBAAkB,CACnC,CAEA,MAAM,mBAAM,CACX,UAAU,CAAE,IAAI,gBAAgB,CACjC,CAEQ,KAAM,CAAC,MAAM,mBAAM,CAC1B,UAAU,CAAE,IAAI,gBAAgB,CACjC,CAEA,MAAM,sBAAS,CACd,UAAU,CAAE,IAAI,iBAAiB,CAClC,CAEQ,KAAM,CAAC,MAAM,sBAAS,CAC7B,UAAU,CAAE,IAAI,iBAAiB,CAClC,CAEA,qBAAQ,CACP,OAAO,CAAE,IACV,CAEA,yBAAW,CAAS,CAAG,CACtB,eAAe,CAAE,SAClB"}'},it$1=create_ssr_component((e,A,t,m)=>{let a,c,{title:l=""}=A,{message:i=""}=A,{type:r}=A,{id:o}=A,{duration:s=10}=A,{visible:u=!0}=A;createEventDispatcher();return A.title===void 0&&t.title&&l!==void 0&&t.title(l),A.message===void 0&&t.message&&i!==void 0&&t.message(i),A.type===void 0&&t.type&&r!==void 0&&t.type(r),A.id===void 0&&t.id&&o!==void 0&&t.id(o),A.duration===void 0&&t.duration&&s!==void 0&&t.duration(s),A.visible===void 0&&t.visible&&u!==void 0&&t.visible(u),e.css.add(Ct),i=st(i),a=u,s=s||null,c=`${s||0}s`,`  <div class="${["toast-body "+escape(r,!0)+" svelte-fee5uc",a?"":"hidden"].join(" ").trim()}" role="alert" data-testid="toast-body"><div class="${"toast-icon "+escape(r,!0)+" svelte-fee5uc"}">${r==="warning"?`${validate_component(xe,"Warning").$$render(e,{},{},{})}`:`${r==="info"?`${validate_component(Pt,"Info").$$render(e,{},{},{})}`:`${r==="success"?`${validate_component(Dt,"Success").$$render(e,{},{},{})}`:`${r==="error"?`${validate_component(Yt,"Error").$$render(e,{},{},{})}`:""}`}`}`}</div> <div class="${"toast-details "+escape(r,!0)+" svelte-fee5uc"}"><div class="${"toast-title "+escape(r,!0)+" svelte-fee5uc"}">${escape(l)}</div> <div class="${"toast-text "+escape(r,!0)+" svelte-fee5uc"}"><!-- HTML_TAG_START -->${i}<!-- HTML_TAG_END --></div></div> <button class="${"toast-close "+escape(r,!0)+" svelte-fee5uc"}" type="button" aria-label="Close" data-testid="toast-close"><span aria-hidden="true" data-svelte-h="svelte-zpkfw7">×</span></button> <div class="${"timer "+escape(r,!0)+" svelte-fee5uc"}"${add_attribute("style",`animation-duration: ${c};`,0)}></div> </div>`}),ct={code:".toast-wrap.svelte-pu0yf1{display:flex;position:fixed;top:var(--size-4);right:var(--size-4);flex-direction:column;align-items:end;gap:var(--size-2);z-index:var(--layer-top);width:calc(100% - var(--size-8))}@media(min-width: 640px){.toast-wrap.svelte-pu0yf1{width:calc(var(--size-96) + var(--size-10))}}",map:'{"version":3,"file":"Toast.svelte","sources":["Toast.svelte"],"sourcesContent":["<script lang=\\"ts\\">import { flip } from \\"svelte/animate\\";\\nimport ToastContent from \\"./ToastContent.svelte\\";\\nexport let messages = [];\\n$: scroll_to_top(messages);\\nfunction scroll_to_top(_messages) {\\n    if (_messages.length > 0) {\\n        if (\\"parentIFrame\\" in window) {\\n            window.parentIFrame?.scrollTo(0, 0);\\n        }\\n    }\\n}\\n<\/script>\\n\\n<div class=\\"toast-wrap\\">\\n\\t{#each messages as { type, title, message, id, duration, visible } (id)}\\n\\t\\t<div animate:flip={{ duration: 300 }} style:width=\\"100%\\">\\n\\t\\t\\t<ToastContent\\n\\t\\t\\t\\t{type}\\n\\t\\t\\t\\t{title}\\n\\t\\t\\t\\t{message}\\n\\t\\t\\t\\t{duration}\\n\\t\\t\\t\\t{visible}\\n\\t\\t\\t\\ton:close\\n\\t\\t\\t\\t{id}\\n\\t\\t\\t/>\\n\\t\\t</div>\\n\\t{/each}\\n</div>\\n\\n<style>\\n\\t.toast-wrap {\\n\\t\\tdisplay: flex;\\n\\t\\tposition: fixed;\\n\\t\\ttop: var(--size-4);\\n\\t\\tright: var(--size-4);\\n\\n\\t\\tflex-direction: column;\\n\\t\\talign-items: end;\\n\\t\\tgap: var(--size-2);\\n\\t\\tz-index: var(--layer-top);\\n\\t\\twidth: calc(100% - var(--size-8));\\n\\t}\\n\\n\\t@media (min-width: 640px) {\\n\\t\\t.toast-wrap {\\n\\t\\t\\twidth: calc(var(--size-96) + var(--size-10));\\n\\t\\t}\\n\\t}</style>\\n"],"names":[],"mappings":"AA8BC,yBAAY,CACX,OAAO,CAAE,IAAI,CACb,QAAQ,CAAE,KAAK,CACf,GAAG,CAAE,IAAI,QAAQ,CAAC,CAClB,KAAK,CAAE,IAAI,QAAQ,CAAC,CAEpB,cAAc,CAAE,MAAM,CACtB,WAAW,CAAE,GAAG,CAChB,GAAG,CAAE,IAAI,QAAQ,CAAC,CAClB,OAAO,CAAE,IAAI,WAAW,CAAC,CACzB,KAAK,CAAE,KAAK,IAAI,CAAC,CAAC,CAAC,IAAI,QAAQ,CAAC,CACjC,CAEA,MAAO,YAAY,KAAK,CAAE,CACzB,yBAAY,CACX,KAAK,CAAE,KAAK,IAAI,SAAS,CAAC,CAAC,CAAC,CAAC,IAAI,SAAS,CAAC,CAC5C,CACD"}'};function dt(e){e.length>0&&"parentIFrame"in window&&window.parentIFrame?.scrollTo(0,0);}const yt=create_ssr_component((e,A,t,m)=>{let{messages:a=[]}=A;return A.messages===void 0&&t.messages&&a!==void 0&&t.messages(a),e.css.add(ct),dt(a),`<div class="toast-wrap svelte-pu0yf1">${each(a,({type:c,title:l,message:i,id:r,duration:o,visible:s})=>`<div${add_styles({width:"100%"})}>${validate_component(it$1,"ToastContent").$$render(e,{type:c,title:l,message:i,duration:o,visible:s,id:r},{},{})} </div>`)} </div>`}),vt={code:".streaming-bar.svelte-roz8lq{position:absolute;bottom:0;left:0;right:0;height:4px;background-color:var(--primary-600);animation:svelte-roz8lq-countdown linear forwards;z-index:1}@keyframes svelte-roz8lq-countdown{from{transform:translateX(0%)}to{transform:translateX(-100%)}}",map:'{"version":3,"file":"StreamingBar.svelte","sources":["StreamingBar.svelte"],"sourcesContent":["<script lang=\\"ts\\">export let time_limit;\\n<\/script>\\n\\n{#if time_limit}\\n\\t<div class=\\"streaming-bar\\" style:animation-duration=\\"{time_limit}s\\"></div>\\n{/if}\\n\\n<style>\\n\\t.streaming-bar {\\n\\t\\tposition: absolute;\\n\\t\\tbottom: 0;\\n\\t\\tleft: 0;\\n\\t\\tright: 0;\\n\\t\\theight: 4px;\\n\\t\\tbackground-color: var(--primary-600);\\n\\t\\tanimation: countdown linear forwards;\\n\\t\\tz-index: 1;\\n\\t}\\n\\n\\t@keyframes countdown {\\n\\t\\tfrom {\\n\\t\\t\\ttransform: translateX(0%);\\n\\t\\t}\\n\\t\\tto {\\n\\t\\t\\ttransform: translateX(-100%);\\n\\t\\t}\\n\\t}</style>\\n"],"names":[],"mappings":"AAQC,4BAAe,CACd,QAAQ,CAAE,QAAQ,CAClB,MAAM,CAAE,CAAC,CACT,IAAI,CAAE,CAAC,CACP,KAAK,CAAE,CAAC,CACR,MAAM,CAAE,GAAG,CACX,gBAAgB,CAAE,IAAI,aAAa,CAAC,CACpC,SAAS,CAAE,uBAAS,CAAC,MAAM,CAAC,QAAQ,CACpC,OAAO,CAAE,CACV,CAEA,WAAW,uBAAU,CACpB,IAAK,CACJ,SAAS,CAAE,WAAW,EAAE,CACzB,CACA,EAAG,CACF,SAAS,CAAE,WAAW,KAAK,CAC5B,CACD"}'},bt=create_ssr_component((e,A,t,m)=>{let{time_limit:a}=A;return A.time_limit===void 0&&t.time_limit&&a!==void 0&&t.time_limit(a),e.css.add(vt),`${a?`<div class="streaming-bar svelte-roz8lq"${add_styles({"animation-duration":`${a}s`})}></div>`:""}`});

class l extends Error{constructor(e){super(e),this.name="ShareError";}}async function _(t,e){if(window.__gradio_space__==null)throw new l("Must be on Spaces to share.");let o,n,i;{let r;if(typeof t=="object"&&t.url)r=t.url;else if(typeof t=="string")r=t;else throw new Error("Invalid data format for URL type");const c=await fetch(r);o=await c.blob(),n=c.headers.get("content-type")||"",i=c.headers.get("content-disposition")||"";}const s=new File([o],i,{type:n}),a=await fetch("https://huggingface.co/uploads",{method:"POST",body:s,headers:{"Content-Type":s.type,"X-Requested-With":"XMLHttpRequest"}});if(!a.ok){if(a.headers.get("content-type")?.includes("application/json")){const r=await a.json();throw new l(`Upload failed: ${r.error}`)}throw new l("Upload failed.")}return await a.text()}const w$1=t=>{const e=Math.floor(t/3600),o=Math.floor(t%3600/60),n=Math.round(t)%60,i=`${o<10?"0":""}${o}`,s=`${n<10?"0":""}${n}`;return e>0?`${e}:${i}:${s}`:`${o}:${s}`},u$1=typeof window<"u";let m$1 = class m{#e;theme;version;i18n;#t;root;autoscroll;max_file_size;client;_load_component;load_component=f$2.bind(this);constructor(e,o,n,i,s,a,h,r=d=>d,c,p){this.#e=e,this.theme=n,this.version=i,this.#t=o,this.max_file_size=h,this.i18n=r,this.root=s,this.autoscroll=a,this.client=c,this._load_component=p;}dispatch(e,o){if(!u$1||!this.#t)return;const n=new CustomEvent("gradio",{bubbles:!0,detail:{data:o,id:this.#e,event:e}});this.#t.dispatchEvent(n);}};function f$2(t,e="component"){return this._load_component({name:t,api_url:this.client.config?.root,variant:e})}const y=t=>typeof t=="number"?t+"px":t;

const a$1={code:"div.svelte-633qhp{display:flex;flex-direction:inherit;flex-wrap:wrap;gap:var(--form-gap-width);box-shadow:var(--block-shadow);border:var(--block-border-width) solid var(--block-border-color);border-radius:var(--block-radius);background:var(--border-color-primary);overflow-y:hidden}div.svelte-633qhp .block{box-shadow:none !important;border-width:0px !important;border-radius:0px !important}.hidden.svelte-633qhp{display:none}",map:'{"version":3,"file":"Index.svelte","sources":["Index.svelte"],"sourcesContent":["<script lang=\\"ts\\">export let visible = true;\\nexport let scale = null;\\nexport let min_width = 0;\\n<\/script>\\n\\n<div\\n\\tclass=\\"form\\"\\n\\tclass:hidden={!visible}\\n\\tstyle:flex-grow={scale}\\n\\tstyle:min-width={`calc(min(${min_width}px, 100%))`}\\n>\\n\\t<slot />\\n</div>\\n\\n<style>\\n\\tdiv {\\n\\t\\tdisplay: flex;\\n\\t\\tflex-direction: inherit;\\n\\t\\tflex-wrap: wrap;\\n\\t\\tgap: var(--form-gap-width);\\n\\t\\tbox-shadow: var(--block-shadow);\\n\\t\\tborder: var(--block-border-width) solid var(--block-border-color);\\n\\t\\tborder-radius: var(--block-radius);\\n\\t\\tbackground: var(--border-color-primary);\\n\\t\\toverflow-y: hidden;\\n\\t}\\n\\n\\tdiv :global(.block) {\\n\\t\\tbox-shadow: none !important;\\n\\t\\tborder-width: 0px !important;\\n\\t\\tborder-radius: 0px !important;\\n\\t}\\n\\n\\t.hidden {\\n\\t\\tdisplay: none;\\n\\t}</style>\\n"],"names":[],"mappings":"AAeC,iBAAI,CACH,OAAO,CAAE,IAAI,CACb,cAAc,CAAE,OAAO,CACvB,SAAS,CAAE,IAAI,CACf,GAAG,CAAE,IAAI,gBAAgB,CAAC,CAC1B,UAAU,CAAE,IAAI,cAAc,CAAC,CAC/B,MAAM,CAAE,IAAI,oBAAoB,CAAC,CAAC,KAAK,CAAC,IAAI,oBAAoB,CAAC,CACjE,aAAa,CAAE,IAAI,cAAc,CAAC,CAClC,UAAU,CAAE,IAAI,sBAAsB,CAAC,CACvC,UAAU,CAAE,MACb,CAEA,iBAAG,CAAS,MAAQ,CACnB,UAAU,CAAE,IAAI,CAAC,UAAU,CAC3B,YAAY,CAAE,GAAG,CAAC,UAAU,CAC5B,aAAa,CAAE,GAAG,CAAC,UACpB,CAEA,qBAAQ,CACP,OAAO,CAAE,IACV"}'},s$1=create_ssr_component((d,A,t,i)=>{let{visible:e=!0}=A,{scale:r=null}=A,{min_width:o=0}=A;return A.visible===void 0&&t.visible&&e!==void 0&&t.visible(e),A.scale===void 0&&t.scale&&r!==void 0&&t.scale(r),A.min_width===void 0&&t.min_width&&o!==void 0&&t.min_width(o),d.css.add(a$1),`<div class="${["form svelte-633qhp",e?"":"hidden"].join(" ").trim()}"${add_styles({"flex-grow":r,"min-width":`calc(min(${o}px, 100%))`})}>${i.default?i.default({}):""} </div>`});

var Index18 = /*#__PURE__*/Object.freeze({
	__proto__: null,
	default: s$1
});

const A$1={code:".gallery.svelte-1oitfqa{padding:var(--size-1) var(--size-2)}div.svelte-1oitfqa{overflow:hidden;white-space:nowrap}",map:'{"version":3,"file":"Example.svelte","sources":["Example.svelte"],"sourcesContent":["<script lang=\\"ts\\">import { onMount } from \\"svelte\\";\\nexport let value;\\nexport let type;\\nexport let selected = false;\\nlet size;\\nlet el;\\nfunction set_styles(element, el_width) {\\n    element.style.setProperty(\\"--local-text-width\\", `${el_width && el_width < 150 ? el_width : 200}px`);\\n    element.style.whiteSpace = \\"unset\\";\\n}\\nfunction truncate_text(text, max_length = 60) {\\n    if (!text)\\n        return \\"\\";\\n    const str = String(text);\\n    if (str.length <= max_length)\\n        return str;\\n    return str.slice(0, max_length) + \\"...\\";\\n}\\nonMount(() => {\\n    set_styles(el, size);\\n});\\n<\/script>\\n\\n<div\\n\\tbind:clientWidth={size}\\n\\tbind:this={el}\\n\\tclass:table={type === \\"table\\"}\\n\\tclass:gallery={type === \\"gallery\\"}\\n\\tclass:selected\\n>\\n\\t{truncate_text(value)}\\n</div>\\n\\n<style>\\n\\t.gallery {\\n\\t\\tpadding: var(--size-1) var(--size-2);\\n\\t}\\n\\n\\tdiv {\\n\\t\\toverflow: hidden;\\n\\t\\twhite-space: nowrap;\\n\\t}</style>\\n"],"names":[],"mappings":"AAkCC,uBAAS,CACR,OAAO,CAAE,IAAI,QAAQ,CAAC,CAAC,IAAI,QAAQ,CACpC,CAEA,kBAAI,CACH,QAAQ,CAAE,MAAM,CAChB,WAAW,CAAE,MACd"}'};function u(l,e=60){if(!l)return "";const t=String(l);return t.length<=e?t:t.slice(0,e)+"..."}const h$1=create_ssr_component((l,e,t,p)=>{let{value:s}=e,{type:n}=e,{selected:i=!1}=e,a;return e.value===void 0&&t.value&&s!==void 0&&t.value(s),e.type===void 0&&t.type&&n!==void 0&&t.type(n),e.selected===void 0&&t.selected&&i!==void 0&&t.selected(i),l.css.add(A$1),`<div class="${["svelte-1oitfqa",(n==="table"?"table":"")+" "+(n==="gallery"?"gallery":"")+" "+(i?"selected":"")].join(" ").trim()}"${add_attribute("this",a,0)}>${escape(u(s))} </div>`});

var Example3 = /*#__PURE__*/Object.freeze({
	__proto__: null,
	default: h$1
});

const V={code:"label.svelte-173056l.svelte-173056l{display:block;width:100%}input.svelte-173056l.svelte-173056l,textarea.svelte-173056l.svelte-173056l{flex-grow:1;outline:none !important;margin-top:0px;margin-bottom:0px;resize:none;z-index:1;display:block;position:relative;outline:none !important;background:var(--input-background-fill);padding:var(--input-padding);width:100%;color:var(--body-text-color);font-weight:var(--input-text-weight);font-size:var(--input-text-size);line-height:var(--line-sm);border:none}textarea.no-label.svelte-173056l.svelte-173056l{padding-top:5px;padding-bottom:5px}label.show_textbox_border.svelte-173056l input.svelte-173056l,label.show_textbox_border.svelte-173056l textarea.svelte-173056l{box-shadow:var(--input-shadow)}label.svelte-173056l.svelte-173056l:not(.container),label.svelte-173056l:not(.container) input.svelte-173056l,label.svelte-173056l:not(.container) textarea.svelte-173056l{height:100%}label.container.show_textbox_border.svelte-173056l input.svelte-173056l,label.container.show_textbox_border.svelte-173056l textarea.svelte-173056l{border:var(--input-border-width) solid var(--input-border-color);border-radius:var(--input-radius)}input.svelte-173056l.svelte-173056l:disabled,textarea.svelte-173056l.svelte-173056l:disabled{-webkit-opacity:1;opacity:1}label.container.show_textbox_border.svelte-173056l input.svelte-173056l:focus,label.container.show_textbox_border.svelte-173056l textarea.svelte-173056l:focus{box-shadow:var(--input-shadow-focus);border-color:var(--input-border-color-focus);background:var(--input-background-fill-focus)}input.svelte-173056l.svelte-173056l::placeholder,textarea.svelte-173056l.svelte-173056l::placeholder{color:var(--input-placeholder-color)}.copy-button.svelte-173056l.svelte-173056l{display:flex;position:absolute;top:var(--block-label-margin);right:var(--block-label-margin);align-items:center;box-shadow:var(--shadow-drop);border:1px solid var(--border-color-primary);border-top:none;border-right:none;border-radius:var(--block-label-right-radius);background:var(--block-label-background-fill);padding:5px;width:22px;height:22px;overflow:hidden;color:var(--block-label-color);font:var(--font-sans);font-size:var(--button-small-text-size)}.input-container.svelte-173056l.svelte-173056l{display:flex;position:relative;align-items:flex-end}.submit-button.svelte-173056l.svelte-173056l,.stop-button.svelte-173056l.svelte-173056l{border:none;text-align:center;text-decoration:none;font-size:14px;cursor:pointer;border-radius:15px;min-width:30px;height:30px;flex-shrink:0;display:flex;justify-content:center;align-items:center;z-index:var(--layer-1)}.stop-button.svelte-173056l.svelte-173056l,.submit-button.svelte-173056l.svelte-173056l{background:var(--button-secondary-background-fill);color:var(--button-secondary-text-color)}.stop-button.svelte-173056l.svelte-173056l:hover,.submit-button.svelte-173056l.svelte-173056l:hover{background:var(--button-secondary-background-fill-hover)}.stop-button.svelte-173056l.svelte-173056l:disabled,.submit-button.svelte-173056l.svelte-173056l:disabled{background:var(--button-secondary-background-fill);cursor:pointer}.stop-button.svelte-173056l.svelte-173056l:active,.submit-button.svelte-173056l.svelte-173056l:active{box-shadow:var(--button-shadow-active)}.submit-button.svelte-173056l svg{height:22px;width:22px}.stop-button.svelte-173056l svg{height:16px;width:16px}.padded-button.svelte-173056l.svelte-173056l{padding:0 10px}",map:'{"version":3,"file":"Textbox.svelte","sources":["Textbox.svelte"],"sourcesContent":["<script lang=\\"ts\\">import { beforeUpdate, afterUpdate, createEventDispatcher, tick } from \\"svelte\\";\\nimport { BlockTitle } from \\"@gradio/atoms\\";\\nimport { Copy, Check, Send, Square } from \\"@gradio/icons\\";\\nimport { fade } from \\"svelte/transition\\";\\nexport let value = \\"\\";\\nexport let value_is_output = false;\\nexport let lines = 1;\\nexport let placeholder = \\"Type here...\\";\\nexport let label;\\nexport let info = void 0;\\nexport let disabled = false;\\nexport let show_label = true;\\nexport let container = true;\\nexport let max_lines = void 0;\\nexport let type = \\"text\\";\\nexport let show_copy_button = false;\\nexport let submit_btn = null;\\nexport let stop_btn = null;\\nexport let rtl = false;\\nexport let autofocus = false;\\nexport let text_align = void 0;\\nexport let autoscroll = true;\\nexport let max_length = void 0;\\nexport let html_attributes = null;\\nlet el;\\nlet copied = false;\\nlet timer;\\nlet can_scroll;\\nlet previous_scroll_top = 0;\\nlet user_has_scrolled_up = false;\\nlet _max_lines;\\nconst show_textbox_border = !submit_btn;\\n$: if (max_lines === void 0 || max_lines === null) {\\n    if (type === \\"text\\") {\\n        _max_lines = Math.max(lines, 20);\\n    }\\n    else {\\n        _max_lines = 1;\\n    }\\n}\\nelse {\\n    _max_lines = Math.max(max_lines, lines);\\n}\\n$: value, el && lines !== _max_lines && resize({ target: el });\\n$: if (value === null)\\n    value = \\"\\";\\nconst dispatch = createEventDispatcher();\\nbeforeUpdate(() => {\\n    if (!user_has_scrolled_up && el && el.offsetHeight + el.scrollTop > el.scrollHeight - 100) {\\n        can_scroll = true;\\n    }\\n});\\nconst scroll = () => {\\n    if (can_scroll && autoscroll && !user_has_scrolled_up) {\\n        el.scrollTo(0, el.scrollHeight);\\n    }\\n};\\nfunction handle_change() {\\n    dispatch(\\"change\\", value);\\n    if (!value_is_output) {\\n        dispatch(\\"input\\");\\n    }\\n}\\nafterUpdate(() => {\\n    if (autofocus) {\\n        el.focus();\\n    }\\n    if (can_scroll && autoscroll) {\\n        scroll();\\n    }\\n    value_is_output = false;\\n});\\n$: value, handle_change();\\nasync function handle_copy() {\\n    if (\\"clipboard\\" in navigator) {\\n        await navigator.clipboard.writeText(value);\\n        dispatch(\\"copy\\", { value });\\n        copy_feedback();\\n    }\\n}\\nfunction copy_feedback() {\\n    copied = true;\\n    if (timer)\\n        clearTimeout(timer);\\n    timer = setTimeout(() => {\\n        copied = false;\\n    }, 1e3);\\n}\\nfunction handle_select(event) {\\n    const target = event.target;\\n    const text = target.value;\\n    const index = [\\n        target.selectionStart,\\n        target.selectionEnd\\n    ];\\n    dispatch(\\"select\\", { value: text.substring(...index), index });\\n}\\nasync function handle_keypress(e) {\\n    await tick();\\n    if (e.key === \\"Enter\\" && e.shiftKey && lines > 1) {\\n        e.preventDefault();\\n        dispatch(\\"submit\\");\\n    }\\n    else if (e.key === \\"Enter\\" && !e.shiftKey && lines === 1 && _max_lines >= 1) {\\n        e.preventDefault();\\n        dispatch(\\"submit\\");\\n    }\\n}\\nfunction handle_scroll(event) {\\n    const target = event.target;\\n    const current_scroll_top = target.scrollTop;\\n    if (current_scroll_top < previous_scroll_top) {\\n        user_has_scrolled_up = true;\\n    }\\n    previous_scroll_top = current_scroll_top;\\n    const max_scroll_top = target.scrollHeight - target.clientHeight;\\n    const user_has_scrolled_to_bottom = current_scroll_top >= max_scroll_top;\\n    if (user_has_scrolled_to_bottom) {\\n        user_has_scrolled_up = false;\\n    }\\n}\\nfunction handle_stop() {\\n    dispatch(\\"stop\\");\\n}\\nfunction handle_submit() {\\n    dispatch(\\"submit\\");\\n}\\nasync function resize(event) {\\n    await tick();\\n    if (lines === _max_lines)\\n        return;\\n    const target = event.target;\\n    const computed_styles = window.getComputedStyle(target);\\n    const padding_top = parseFloat(computed_styles.paddingTop);\\n    const padding_bottom = parseFloat(computed_styles.paddingBottom);\\n    const line_height = parseFloat(computed_styles.lineHeight);\\n    let max = _max_lines === void 0 ? false : padding_top + padding_bottom + line_height * _max_lines;\\n    let min = padding_top + padding_bottom + lines * line_height;\\n    target.style.height = \\"1px\\";\\n    let scroll_height;\\n    if (max && target.scrollHeight > max) {\\n        scroll_height = max;\\n    }\\n    else if (target.scrollHeight < min) {\\n        scroll_height = min;\\n    }\\n    else {\\n        scroll_height = target.scrollHeight;\\n    }\\n    target.style.height = `${scroll_height}px`;\\n    update_scrollbar_visibility(target);\\n}\\nfunction update_scrollbar_visibility(textarea) {\\n    const content_height = textarea.scrollHeight;\\n    const visible_height = textarea.clientHeight;\\n    const line_height = parseFloat(window.getComputedStyle(textarea).lineHeight);\\n    if (content_height > visible_height + line_height) {\\n        textarea.style.overflowY = \\"scroll\\";\\n    }\\n    else {\\n        textarea.style.overflowY = \\"hidden\\";\\n    }\\n}\\nfunction text_area_resize(_el, _value) {\\n    if (lines === _max_lines)\\n        return;\\n    _el.style.overflowY = \\"scroll\\";\\n    _el.addEventListener(\\"input\\", resize);\\n    if (!_value.trim())\\n        return;\\n    resize({ target: _el });\\n    return {\\n        destroy: () => _el.removeEventListener(\\"input\\", resize)\\n    };\\n}\\n<\/script>\\n\\n<!-- svelte-ignore a11y-autofocus -->\\n<label class:container class:show_textbox_border>\\n\\t{#if show_label && show_copy_button}\\n\\t\\t{#if copied}\\n\\t\\t\\t<button\\n\\t\\t\\t\\tin:fade={{ duration: 300 }}\\n\\t\\t\\t\\tclass=\\"copy-button\\"\\n\\t\\t\\t\\taria-label=\\"Copied\\"\\n\\t\\t\\t\\taria-roledescription=\\"Text copied\\"><Check /></button\\n\\t\\t\\t>\\n\\t\\t{:else}\\n\\t\\t\\t<button\\n\\t\\t\\t\\ton:click={handle_copy}\\n\\t\\t\\t\\tclass=\\"copy-button\\"\\n\\t\\t\\t\\taria-label=\\"Copy\\"\\n\\t\\t\\t\\taria-roledescription=\\"Copy text\\"><Copy /></button\\n\\t\\t\\t>\\n\\t\\t{/if}\\n\\t{/if}\\n\\t<BlockTitle {show_label} {info}>{label}</BlockTitle>\\n\\n\\t<div class=\\"input-container\\">\\n\\t\\t{#if lines === 1 && _max_lines === 1}\\n\\t\\t\\t{#if type === \\"text\\"}\\n\\t\\t\\t\\t<input\\n\\t\\t\\t\\t\\tdata-testid=\\"textbox\\"\\n\\t\\t\\t\\t\\ttype=\\"text\\"\\n\\t\\t\\t\\t\\tclass=\\"scroll-hide\\"\\n\\t\\t\\t\\t\\tdir={rtl ? \\"rtl\\" : \\"ltr\\"}\\n\\t\\t\\t\\t\\tbind:value\\n\\t\\t\\t\\t\\tbind:this={el}\\n\\t\\t\\t\\t\\t{placeholder}\\n\\t\\t\\t\\t\\t{disabled}\\n\\t\\t\\t\\t\\t{autofocus}\\n\\t\\t\\t\\t\\tmaxlength={max_length}\\n\\t\\t\\t\\t\\ton:keypress={handle_keypress}\\n\\t\\t\\t\\t\\ton:blur\\n\\t\\t\\t\\t\\ton:select={handle_select}\\n\\t\\t\\t\\t\\ton:focus\\n\\t\\t\\t\\t\\tstyle={text_align ? \\"text-align: \\" + text_align : \\"\\"}\\n\\t\\t\\t\\t\\tautocapitalize={html_attributes?.autocapitalize}\\n\\t\\t\\t\\t\\tautocorrect={html_attributes?.autocorrect}\\n\\t\\t\\t\\t\\tspellcheck={html_attributes?.spellcheck}\\n\\t\\t\\t\\t\\tautocomplete={html_attributes?.autocomplete}\\n\\t\\t\\t\\t\\ttabindex={html_attributes?.tabindex}\\n\\t\\t\\t\\t\\tenterkeyhint={html_attributes?.enterkeyhint}\\n\\t\\t\\t\\t\\tlang={html_attributes?.lang}\\n\\t\\t\\t\\t/>\\n\\t\\t\\t{:else if type === \\"password\\"}\\n\\t\\t\\t\\t<input\\n\\t\\t\\t\\t\\tdata-testid=\\"password\\"\\n\\t\\t\\t\\t\\ttype=\\"password\\"\\n\\t\\t\\t\\t\\tclass=\\"scroll-hide\\"\\n\\t\\t\\t\\t\\tbind:value\\n\\t\\t\\t\\t\\tbind:this={el}\\n\\t\\t\\t\\t\\t{placeholder}\\n\\t\\t\\t\\t\\t{disabled}\\n\\t\\t\\t\\t\\t{autofocus}\\n\\t\\t\\t\\t\\tmaxlength={max_length}\\n\\t\\t\\t\\t\\ton:keypress={handle_keypress}\\n\\t\\t\\t\\t\\ton:blur\\n\\t\\t\\t\\t\\ton:select={handle_select}\\n\\t\\t\\t\\t\\ton:focus\\n\\t\\t\\t\\t\\tautocomplete=\\"\\"\\n\\t\\t\\t\\t\\tautocapitalize={html_attributes?.autocapitalize}\\n\\t\\t\\t\\t\\tautocorrect={html_attributes?.autocorrect}\\n\\t\\t\\t\\t\\tspellcheck={html_attributes?.spellcheck}\\n\\t\\t\\t\\t\\ttabindex={html_attributes?.tabindex}\\n\\t\\t\\t\\t\\tenterkeyhint={html_attributes?.enterkeyhint}\\n\\t\\t\\t\\t\\tlang={html_attributes?.lang}\\n\\t\\t\\t\\t/>\\n\\t\\t\\t{:else if type === \\"email\\"}\\n\\t\\t\\t\\t<input\\n\\t\\t\\t\\t\\tdata-testid=\\"textbox\\"\\n\\t\\t\\t\\t\\ttype=\\"email\\"\\n\\t\\t\\t\\t\\tclass=\\"scroll-hide\\"\\n\\t\\t\\t\\t\\tbind:value\\n\\t\\t\\t\\t\\tbind:this={el}\\n\\t\\t\\t\\t\\t{placeholder}\\n\\t\\t\\t\\t\\t{disabled}\\n\\t\\t\\t\\t\\t{autofocus}\\n\\t\\t\\t\\t\\tmaxlength={max_length}\\n\\t\\t\\t\\t\\ton:keypress={handle_keypress}\\n\\t\\t\\t\\t\\ton:blur\\n\\t\\t\\t\\t\\ton:select={handle_select}\\n\\t\\t\\t\\t\\ton:focus\\n\\t\\t\\t\\t\\tautocomplete=\\"email\\"\\n\\t\\t\\t\\t\\tautocapitalize={html_attributes?.autocapitalize}\\n\\t\\t\\t\\t\\tautocorrect={html_attributes?.autocorrect}\\n\\t\\t\\t\\t\\tspellcheck={html_attributes?.spellcheck}\\n\\t\\t\\t\\t\\ttabindex={html_attributes?.tabindex}\\n\\t\\t\\t\\t\\tenterkeyhint={html_attributes?.enterkeyhint}\\n\\t\\t\\t\\t\\tlang={html_attributes?.lang}\\n\\t\\t\\t\\t/>\\n\\t\\t\\t{/if}\\n\\t\\t{:else}\\n\\t\\t\\t<textarea\\n\\t\\t\\t\\tdata-testid=\\"textbox\\"\\n\\t\\t\\t\\tuse:text_area_resize={value}\\n\\t\\t\\t\\tdir={rtl ? \\"rtl\\" : \\"ltr\\"}\\n\\t\\t\\t\\tclass:no-label={!show_label && (submit_btn || stop_btn)}\\n\\t\\t\\t\\tbind:value\\n\\t\\t\\t\\tbind:this={el}\\n\\t\\t\\t\\t{placeholder}\\n\\t\\t\\t\\trows={lines}\\n\\t\\t\\t\\t{disabled}\\n\\t\\t\\t\\t{autofocus}\\n\\t\\t\\t\\tmaxlength={max_length}\\n\\t\\t\\t\\ton:keypress={handle_keypress}\\n\\t\\t\\t\\ton:blur\\n\\t\\t\\t\\ton:select={handle_select}\\n\\t\\t\\t\\ton:focus\\n\\t\\t\\t\\ton:scroll={handle_scroll}\\n\\t\\t\\t\\tstyle={text_align ? \\"text-align: \\" + text_align : \\"\\"}\\n\\t\\t\\t\\tautocapitalize={html_attributes?.autocapitalize}\\n\\t\\t\\t\\tautocorrect={html_attributes?.autocorrect}\\n\\t\\t\\t\\tspellcheck={html_attributes?.spellcheck}\\n\\t\\t\\t\\tautocomplete={html_attributes?.autocomplete}\\n\\t\\t\\t\\ttabindex={html_attributes?.tabindex}\\n\\t\\t\\t\\tenterkeyhint={html_attributes?.enterkeyhint}\\n\\t\\t\\t\\tlang={html_attributes?.lang}\\n\\t\\t\\t/>\\n\\t\\t{/if}\\n\\t\\t{#if submit_btn}\\n\\t\\t\\t<button\\n\\t\\t\\t\\tclass=\\"submit-button\\"\\n\\t\\t\\t\\tclass:padded-button={submit_btn !== true}\\n\\t\\t\\t\\ton:click={handle_submit}\\n\\t\\t\\t>\\n\\t\\t\\t\\t{#if submit_btn === true}\\n\\t\\t\\t\\t\\t<Send />\\n\\t\\t\\t\\t{:else}\\n\\t\\t\\t\\t\\t{submit_btn}\\n\\t\\t\\t\\t{/if}\\n\\t\\t\\t</button>\\n\\t\\t{/if}\\n\\t\\t{#if stop_btn}\\n\\t\\t\\t<button\\n\\t\\t\\t\\tclass=\\"stop-button\\"\\n\\t\\t\\t\\tclass:padded-button={stop_btn !== true}\\n\\t\\t\\t\\ton:click={handle_stop}\\n\\t\\t\\t>\\n\\t\\t\\t\\t{#if stop_btn === true}\\n\\t\\t\\t\\t\\t<Square fill=\\"none\\" stroke_width={2.5} />\\n\\t\\t\\t\\t{:else}\\n\\t\\t\\t\\t\\t{stop_btn}\\n\\t\\t\\t\\t{/if}\\n\\t\\t\\t</button>\\n\\t\\t{/if}\\n\\t</div>\\n</label>\\n\\n<style>\\n\\tlabel {\\n\\t\\tdisplay: block;\\n\\t\\twidth: 100%;\\n\\t}\\n\\n\\tinput,\\n\\ttextarea {\\n\\t\\tflex-grow: 1;\\n\\t\\toutline: none !important;\\n\\t\\tmargin-top: 0px;\\n\\t\\tmargin-bottom: 0px;\\n\\t\\tresize: none;\\n\\t\\tz-index: 1;\\n\\t\\tdisplay: block;\\n\\t\\tposition: relative;\\n\\t\\toutline: none !important;\\n\\t\\tbackground: var(--input-background-fill);\\n\\t\\tpadding: var(--input-padding);\\n\\t\\twidth: 100%;\\n\\t\\tcolor: var(--body-text-color);\\n\\t\\tfont-weight: var(--input-text-weight);\\n\\t\\tfont-size: var(--input-text-size);\\n\\t\\tline-height: var(--line-sm);\\n\\t\\tborder: none;\\n\\t}\\n\\ttextarea.no-label {\\n\\t\\tpadding-top: 5px;\\n\\t\\tpadding-bottom: 5px;\\n\\t}\\n\\tlabel.show_textbox_border input,\\n\\tlabel.show_textbox_border textarea {\\n\\t\\tbox-shadow: var(--input-shadow);\\n\\t}\\n\\tlabel:not(.container),\\n\\tlabel:not(.container) input,\\n\\tlabel:not(.container) textarea {\\n\\t\\theight: 100%;\\n\\t}\\n\\tlabel.container.show_textbox_border input,\\n\\tlabel.container.show_textbox_border textarea {\\n\\t\\tborder: var(--input-border-width) solid var(--input-border-color);\\n\\t\\tborder-radius: var(--input-radius);\\n\\t}\\n\\tinput:disabled,\\n\\ttextarea:disabled {\\n\\t\\t-webkit-opacity: 1;\\n\\t\\topacity: 1;\\n\\t}\\n\\n\\tlabel.container.show_textbox_border input:focus,\\n\\tlabel.container.show_textbox_border textarea:focus {\\n\\t\\tbox-shadow: var(--input-shadow-focus);\\n\\t\\tborder-color: var(--input-border-color-focus);\\n\\t\\tbackground: var(--input-background-fill-focus);\\n\\t}\\n\\n\\tinput::placeholder,\\n\\ttextarea::placeholder {\\n\\t\\tcolor: var(--input-placeholder-color);\\n\\t}\\n\\n\\t.copy-button {\\n\\t\\tdisplay: flex;\\n\\t\\tposition: absolute;\\n\\t\\ttop: var(--block-label-margin);\\n\\t\\tright: var(--block-label-margin);\\n\\t\\talign-items: center;\\n\\t\\tbox-shadow: var(--shadow-drop);\\n\\t\\tborder: 1px solid var(--border-color-primary);\\n\\t\\tborder-top: none;\\n\\t\\tborder-right: none;\\n\\t\\tborder-radius: var(--block-label-right-radius);\\n\\t\\tbackground: var(--block-label-background-fill);\\n\\t\\tpadding: 5px;\\n\\t\\twidth: 22px;\\n\\t\\theight: 22px;\\n\\t\\toverflow: hidden;\\n\\t\\tcolor: var(--block-label-color);\\n\\t\\tfont: var(--font-sans);\\n\\t\\tfont-size: var(--button-small-text-size);\\n\\t}\\n\\n\\t/* Same submit button style as MultimodalTextbox for the consistent UI */\\n\\t.input-container {\\n\\t\\tdisplay: flex;\\n\\t\\tposition: relative;\\n\\t\\talign-items: flex-end;\\n\\t}\\n\\t.submit-button,\\n\\t.stop-button {\\n\\t\\tborder: none;\\n\\t\\ttext-align: center;\\n\\t\\ttext-decoration: none;\\n\\t\\tfont-size: 14px;\\n\\t\\tcursor: pointer;\\n\\t\\tborder-radius: 15px;\\n\\t\\tmin-width: 30px;\\n\\t\\theight: 30px;\\n\\t\\tflex-shrink: 0;\\n\\t\\tdisplay: flex;\\n\\t\\tjustify-content: center;\\n\\t\\talign-items: center;\\n\\t\\tz-index: var(--layer-1);\\n\\t}\\n\\t.stop-button,\\n\\t.submit-button {\\n\\t\\tbackground: var(--button-secondary-background-fill);\\n\\t\\tcolor: var(--button-secondary-text-color);\\n\\t}\\n\\t.stop-button:hover,\\n\\t.submit-button:hover {\\n\\t\\tbackground: var(--button-secondary-background-fill-hover);\\n\\t}\\n\\t.stop-button:disabled,\\n\\t.submit-button:disabled {\\n\\t\\tbackground: var(--button-secondary-background-fill);\\n\\t\\tcursor: pointer;\\n\\t}\\n\\t.stop-button:active,\\n\\t.submit-button:active {\\n\\t\\tbox-shadow: var(--button-shadow-active);\\n\\t}\\n\\t.submit-button :global(svg) {\\n\\t\\theight: 22px;\\n\\t\\twidth: 22px;\\n\\t}\\n\\n\\t.stop-button :global(svg) {\\n\\t\\theight: 16px;\\n\\t\\twidth: 16px;\\n\\t}\\n\\t.padded-button {\\n\\t\\tpadding: 0 10px;\\n\\t}</style>\\n"],"names":[],"mappings":"AA0UC,mCAAM,CACL,OAAO,CAAE,KAAK,CACd,KAAK,CAAE,IACR,CAEA,mCAAK,CACL,sCAAS,CACR,SAAS,CAAE,CAAC,CACZ,OAAO,CAAE,IAAI,CAAC,UAAU,CACxB,UAAU,CAAE,GAAG,CACf,aAAa,CAAE,GAAG,CAClB,MAAM,CAAE,IAAI,CACZ,OAAO,CAAE,CAAC,CACV,OAAO,CAAE,KAAK,CACd,QAAQ,CAAE,QAAQ,CAClB,OAAO,CAAE,IAAI,CAAC,UAAU,CACxB,UAAU,CAAE,IAAI,uBAAuB,CAAC,CACxC,OAAO,CAAE,IAAI,eAAe,CAAC,CAC7B,KAAK,CAAE,IAAI,CACX,KAAK,CAAE,IAAI,iBAAiB,CAAC,CAC7B,WAAW,CAAE,IAAI,mBAAmB,CAAC,CACrC,SAAS,CAAE,IAAI,iBAAiB,CAAC,CACjC,WAAW,CAAE,IAAI,SAAS,CAAC,CAC3B,MAAM,CAAE,IACT,CACA,QAAQ,uCAAU,CACjB,WAAW,CAAE,GAAG,CAChB,cAAc,CAAE,GACjB,CACA,KAAK,mCAAoB,CAAC,oBAAK,CAC/B,KAAK,mCAAoB,CAAC,uBAAS,CAClC,UAAU,CAAE,IAAI,cAAc,CAC/B,CACA,mCAAK,KAAK,UAAU,CAAC,CACrB,oBAAK,KAAK,UAAU,CAAC,CAAC,oBAAK,CAC3B,oBAAK,KAAK,UAAU,CAAC,CAAC,uBAAS,CAC9B,MAAM,CAAE,IACT,CACA,KAAK,UAAU,mCAAoB,CAAC,oBAAK,CACzC,KAAK,UAAU,mCAAoB,CAAC,uBAAS,CAC5C,MAAM,CAAE,IAAI,oBAAoB,CAAC,CAAC,KAAK,CAAC,IAAI,oBAAoB,CAAC,CACjE,aAAa,CAAE,IAAI,cAAc,CAClC,CACA,mCAAK,SAAS,CACd,sCAAQ,SAAU,CACjB,eAAe,CAAE,CAAC,CAClB,OAAO,CAAE,CACV,CAEA,KAAK,UAAU,mCAAoB,CAAC,oBAAK,MAAM,CAC/C,KAAK,UAAU,mCAAoB,CAAC,uBAAQ,MAAO,CAClD,UAAU,CAAE,IAAI,oBAAoB,CAAC,CACrC,YAAY,CAAE,IAAI,0BAA0B,CAAC,CAC7C,UAAU,CAAE,IAAI,6BAA6B,CAC9C,CAEA,mCAAK,aAAa,CAClB,sCAAQ,aAAc,CACrB,KAAK,CAAE,IAAI,yBAAyB,CACrC,CAEA,0CAAa,CACZ,OAAO,CAAE,IAAI,CACb,QAAQ,CAAE,QAAQ,CAClB,GAAG,CAAE,IAAI,oBAAoB,CAAC,CAC9B,KAAK,CAAE,IAAI,oBAAoB,CAAC,CAChC,WAAW,CAAE,MAAM,CACnB,UAAU,CAAE,IAAI,aAAa,CAAC,CAC9B,MAAM,CAAE,GAAG,CAAC,KAAK,CAAC,IAAI,sBAAsB,CAAC,CAC7C,UAAU,CAAE,IAAI,CAChB,YAAY,CAAE,IAAI,CAClB,aAAa,CAAE,IAAI,0BAA0B,CAAC,CAC9C,UAAU,CAAE,IAAI,6BAA6B,CAAC,CAC9C,OAAO,CAAE,GAAG,CACZ,KAAK,CAAE,IAAI,CACX,MAAM,CAAE,IAAI,CACZ,QAAQ,CAAE,MAAM,CAChB,KAAK,CAAE,IAAI,mBAAmB,CAAC,CAC/B,IAAI,CAAE,IAAI,WAAW,CAAC,CACtB,SAAS,CAAE,IAAI,wBAAwB,CACxC,CAGA,8CAAiB,CAChB,OAAO,CAAE,IAAI,CACb,QAAQ,CAAE,QAAQ,CAClB,WAAW,CAAE,QACd,CACA,4CAAc,CACd,0CAAa,CACZ,MAAM,CAAE,IAAI,CACZ,UAAU,CAAE,MAAM,CAClB,eAAe,CAAE,IAAI,CACrB,SAAS,CAAE,IAAI,CACf,MAAM,CAAE,OAAO,CACf,aAAa,CAAE,IAAI,CACnB,SAAS,CAAE,IAAI,CACf,MAAM,CAAE,IAAI,CACZ,WAAW,CAAE,CAAC,CACd,OAAO,CAAE,IAAI,CACb,eAAe,CAAE,MAAM,CACvB,WAAW,CAAE,MAAM,CACnB,OAAO,CAAE,IAAI,SAAS,CACvB,CACA,0CAAY,CACZ,4CAAe,CACd,UAAU,CAAE,IAAI,kCAAkC,CAAC,CACnD,KAAK,CAAE,IAAI,6BAA6B,CACzC,CACA,0CAAY,MAAM,CAClB,4CAAc,MAAO,CACpB,UAAU,CAAE,IAAI,wCAAwC,CACzD,CACA,0CAAY,SAAS,CACrB,4CAAc,SAAU,CACvB,UAAU,CAAE,IAAI,kCAAkC,CAAC,CACnD,MAAM,CAAE,OACT,CACA,0CAAY,OAAO,CACnB,4CAAc,OAAQ,CACrB,UAAU,CAAE,IAAI,sBAAsB,CACvC,CACA,6BAAc,CAAS,GAAK,CAC3B,MAAM,CAAE,IAAI,CACZ,KAAK,CAAE,IACR,CAEA,2BAAY,CAAS,GAAK,CACzB,MAAM,CAAE,IAAI,CACZ,KAAK,CAAE,IACR,CACA,4CAAe,CACd,OAAO,CAAE,CAAC,CAAC,IACZ"}'},X=create_ssr_component((A,t,e,G)=>{let{value:o=""}=t,{value_is_output:x=!1}=t,{lines:u=1}=t,{placeholder:d="Type here..."}=t,{label:f}=t,{info:y=void 0}=t,{disabled:i=!1}=t,{show_label:h=!0}=t,{container:g=!0}=t,{max_lines:v=void 0}=t,{type:C="text"}=t,{show_copy_button:B=!1}=t,{submit_btn:a=null}=t,{stop_btn:r=null}=t,{rtl:m=!1}=t,{autofocus:s=!1}=t,{text_align:b=void 0}=t,{autoscroll:k=!0}=t,{max_length:c=void 0}=t,{html_attributes:n=null}=t,_,p;const E=!a,I=createEventDispatcher();function K(){I("change",o),x||I("input");}return t.value===void 0&&e.value&&o!==void 0&&e.value(o),t.value_is_output===void 0&&e.value_is_output&&x!==void 0&&e.value_is_output(x),t.lines===void 0&&e.lines&&u!==void 0&&e.lines(u),t.placeholder===void 0&&e.placeholder&&d!==void 0&&e.placeholder(d),t.label===void 0&&e.label&&f!==void 0&&e.label(f),t.info===void 0&&e.info&&y!==void 0&&e.info(y),t.disabled===void 0&&e.disabled&&i!==void 0&&e.disabled(i),t.show_label===void 0&&e.show_label&&h!==void 0&&e.show_label(h),t.container===void 0&&e.container&&g!==void 0&&e.container(g),t.max_lines===void 0&&e.max_lines&&v!==void 0&&e.max_lines(v),t.type===void 0&&e.type&&C!==void 0&&e.type(C),t.show_copy_button===void 0&&e.show_copy_button&&B!==void 0&&e.show_copy_button(B),t.submit_btn===void 0&&e.submit_btn&&a!==void 0&&e.submit_btn(a),t.stop_btn===void 0&&e.stop_btn&&r!==void 0&&e.stop_btn(r),t.rtl===void 0&&e.rtl&&m!==void 0&&e.rtl(m),t.autofocus===void 0&&e.autofocus&&s!==void 0&&e.autofocus(s),t.text_align===void 0&&e.text_align&&b!==void 0&&e.text_align(b),t.autoscroll===void 0&&e.autoscroll&&k!==void 0&&e.autoscroll(k),t.max_length===void 0&&e.max_length&&c!==void 0&&e.max_length(c),t.html_attributes===void 0&&e.html_attributes&&n!==void 0&&e.html_attributes(n),A.css.add(V),v==null?C==="text"?p=Math.max(u,20):p=1:p=Math.max(v,u),o===null&&(o=""),K(),` <label class="${["svelte-173056l",(g?"container":"")+" "+(E?"show_textbox_border":"")].join(" ").trim()}">${h&&B?`${`<button class="copy-button svelte-173056l" aria-label="Copy" aria-roledescription="Copy text">${validate_component(Zt,"Copy").$$render(A,{},{},{})}</button>`}`:""} ${validate_component(xt,"BlockTitle").$$render(A,{show_label:h,info:y},{},{default:()=>`${escape(f)}`})} <div class="input-container svelte-173056l">${u===1&&p===1?`${C==="text"?`<input data-testid="textbox" type="text" class="scroll-hide svelte-173056l"${add_attribute("dir",m?"rtl":"ltr",0)}${add_attribute("placeholder",d,0)} ${i?"disabled":""} ${s?"autofocus":""}${add_attribute("maxlength",c,0)}${add_attribute("style",b?"text-align: "+b:"",0)}${add_attribute("autocapitalize",n?.autocapitalize,0)}${add_attribute("autocorrect",n?.autocorrect,0)}${add_attribute("spellcheck",n?.spellcheck,0)}${add_attribute("autocomplete",n?.autocomplete,0)}${add_attribute("tabindex",n?.tabindex,0)}${add_attribute("enterkeyhint",n?.enterkeyhint,0)}${add_attribute("lang",n?.lang,0)}${add_attribute("value",o,0)}${add_attribute("this",_,0)}>`:`${C==="password"?`<input data-testid="password" type="password" class="scroll-hide svelte-173056l"${add_attribute("placeholder",d,0)} ${i?"disabled":""} ${s?"autofocus":""}${add_attribute("maxlength",c,0)} autocomplete=""${add_attribute("autocapitalize",n?.autocapitalize,0)}${add_attribute("autocorrect",n?.autocorrect,0)}${add_attribute("spellcheck",n?.spellcheck,0)}${add_attribute("tabindex",n?.tabindex,0)}${add_attribute("enterkeyhint",n?.enterkeyhint,0)}${add_attribute("lang",n?.lang,0)}${add_attribute("value",o,0)}${add_attribute("this",_,0)}>`:`${C==="email"?`<input data-testid="textbox" type="email" class="scroll-hide svelte-173056l"${add_attribute("placeholder",d,0)} ${i?"disabled":""} ${s?"autofocus":""}${add_attribute("maxlength",c,0)} autocomplete="email"${add_attribute("autocapitalize",n?.autocapitalize,0)}${add_attribute("autocorrect",n?.autocorrect,0)}${add_attribute("spellcheck",n?.spellcheck,0)}${add_attribute("tabindex",n?.tabindex,0)}${add_attribute("enterkeyhint",n?.enterkeyhint,0)}${add_attribute("lang",n?.lang,0)}${add_attribute("value",o,0)}${add_attribute("this",_,0)}>`:""}`}`}`:`<textarea data-testid="textbox"${add_attribute("dir",m?"rtl":"ltr",0)}${add_attribute("placeholder",d,0)}${add_attribute("rows",u,0)} ${i?"disabled":""} ${s?"autofocus":""}${add_attribute("maxlength",c,0)}${add_attribute("style",b?"text-align: "+b:"",0)}${add_attribute("autocapitalize",n?.autocapitalize,0)}${add_attribute("autocorrect",n?.autocorrect,0)}${add_attribute("spellcheck",n?.spellcheck,0)}${add_attribute("autocomplete",n?.autocomplete,0)}${add_attribute("tabindex",n?.tabindex,0)}${add_attribute("enterkeyhint",n?.enterkeyhint,0)}${add_attribute("lang",n?.lang,0)} class="${["svelte-173056l",!h&&(a||r)?"no-label":""].join(" ").trim()}"${add_attribute("this",_,0)}>${escape(o||"")}</textarea>`} ${a?`<button class="${["submit-button svelte-173056l",a!==!0?"padded-button":""].join(" ").trim()}">${a===!0?`${validate_component(ae,"Send").$$render(A,{},{},{})}`:`${escape(a)}`}</button>`:""} ${r?`<button class="${["stop-button svelte-173056l",r!==!0?"padded-button":""].join(" ").trim()}">${r===!0?`${validate_component(de,"Square").$$render(A,{fill:"none",stroke_width:2.5},{},{})}`:`${escape(r)}`}</button>`:""}</div> </label>`}),et=create_ssr_component((A,t,e,G)=>{let{gradio:o}=t,{label:x="Textbox"}=t,{info:u=void 0}=t,{elem_id:d=""}=t,{elem_classes:f=[]}=t,{visible:y=!0}=t,{value:i=""}=t,{lines:h}=t,{placeholder:g=""}=t,{show_label:v}=t,{max_lines:C=void 0}=t,{type:B="text"}=t,{container:a=!0}=t,{scale:r=null}=t,{min_width:m=void 0}=t,{submit_btn:s=null}=t,{stop_btn:b=null}=t,{show_copy_button:k=!1}=t,{loading_status:c=void 0}=t,{value_is_output:n=!1}=t,{rtl:_=!1}=t,{text_align:p=void 0}=t,{autofocus:E=!1}=t,{autoscroll:I=!0}=t,{interactive:K}=t,{max_length:z=void 0}=t,{html_attributes:S=null}=t;t.gradio===void 0&&e.gradio&&o!==void 0&&e.gradio(o),t.label===void 0&&e.label&&x!==void 0&&e.label(x),t.info===void 0&&e.info&&u!==void 0&&e.info(u),t.elem_id===void 0&&e.elem_id&&d!==void 0&&e.elem_id(d),t.elem_classes===void 0&&e.elem_classes&&f!==void 0&&e.elem_classes(f),t.visible===void 0&&e.visible&&y!==void 0&&e.visible(y),t.value===void 0&&e.value&&i!==void 0&&e.value(i),t.lines===void 0&&e.lines&&h!==void 0&&e.lines(h),t.placeholder===void 0&&e.placeholder&&g!==void 0&&e.placeholder(g),t.show_label===void 0&&e.show_label&&v!==void 0&&e.show_label(v),t.max_lines===void 0&&e.max_lines&&C!==void 0&&e.max_lines(C),t.type===void 0&&e.type&&B!==void 0&&e.type(B),t.container===void 0&&e.container&&a!==void 0&&e.container(a),t.scale===void 0&&e.scale&&r!==void 0&&e.scale(r),t.min_width===void 0&&e.min_width&&m!==void 0&&e.min_width(m),t.submit_btn===void 0&&e.submit_btn&&s!==void 0&&e.submit_btn(s),t.stop_btn===void 0&&e.stop_btn&&b!==void 0&&e.stop_btn(b),t.show_copy_button===void 0&&e.show_copy_button&&k!==void 0&&e.show_copy_button(k),t.loading_status===void 0&&e.loading_status&&c!==void 0&&e.loading_status(c),t.value_is_output===void 0&&e.value_is_output&&n!==void 0&&e.value_is_output(n),t.rtl===void 0&&e.rtl&&_!==void 0&&e.rtl(_),t.text_align===void 0&&e.text_align&&p!==void 0&&e.text_align(p),t.autofocus===void 0&&e.autofocus&&E!==void 0&&e.autofocus(E),t.autoscroll===void 0&&e.autoscroll&&I!==void 0&&e.autoscroll(I),t.interactive===void 0&&e.interactive&&K!==void 0&&e.interactive(K),t.max_length===void 0&&e.max_length&&z!==void 0&&e.max_length(z),t.html_attributes===void 0&&e.html_attributes&&S!==void 0&&e.html_attributes(S);let U,T,W=A.head;do U=!0,A.head=W,T=`   ${validate_component(mt,"Block").$$render(A,{visible:y,elem_id:d,elem_classes:f,scale:r,min_width:m,allow_overflow:!1,padding:a},{},{default:()=>`${c?`${validate_component(Et,"StatusTracker").$$render(A,Object.assign({},{autoscroll:o.autoscroll},{i18n:o.i18n},c),{},{})}`:""} ${validate_component(X,"TextBox").$$render(A,{label:x,info:u,show_label:v,lines:h,type:B,rtl:_,text_align:p,max_lines:C,placeholder:g,submit_btn:s,stop_btn:b,show_copy_button:k,autofocus:E,container:a,autoscroll:I,max_length:z,html_attributes:S,disabled:!K,value:i,value_is_output:n},{value:O=>{i=O,U=!1;},value_is_output:O=>{n=O,U=!1;}},{})}`})}`;while(!U);return T});

var Index24 = /*#__PURE__*/Object.freeze({
	__proto__: null,
	BaseExample: h$1,
	BaseTextbox: X,
	default: et
});

const b$1="WORKER_PROXY_CONTEXT_KEY";function f$1(){return getContext(b$1)}const m="lite.local";function k$1(e){return e.host===window.location.host||e.host==="localhost:7860"||e.host==="127.0.0.1:7860"||e.host===m}function v(e,t){const n=t.toLowerCase();for(const[o,r]of Object.entries(e))if(o.toLowerCase()===n)return r}function w(e){const t=typeof window<"u";if(e==null||!t)return !1;const n=new URL(e,window.location.href);return !(!k$1(n)||n.protocol!=="http:"&&n.protocol!=="https:")}let i;async function A(e){const t=typeof window<"u";if(e==null||!t||!w(e))return e;if(i==null)try{i=f$1();}catch{return e}if(i==null)return e;const o=new URL(e,window.location.href).pathname;return i.httpRequest({method:"GET",path:o,headers:{},query_string:""}).then(r=>{if(r.status!==200)throw new Error(`Failed to get file ${o} from the Wasm worker.`);const l=new Blob([r.body],{type:v(r.headers,"content-type")});return URL.createObjectURL(l)})}const x$1={code:".unstyled-link.svelte-1s8vnbx{all:unset;cursor:pointer}",map:'{"version":3,"file":"DownloadLink.svelte","sources":["DownloadLink.svelte"],"sourcesContent":["<script lang=\\"ts\\">import { createEventDispatcher, onMount } from \\"svelte\\";\\nimport { getWorkerProxyContext } from \\"./context\\";\\nimport { should_proxy_wasm_src } from \\"./file-url\\";\\nimport { getHeaderValue } from \\"../src/http\\";\\nexport let href = void 0;\\nexport let download;\\nconst dispatch = createEventDispatcher();\\nlet is_downloading = false;\\nconst worker_proxy = getWorkerProxyContext();\\nasync function wasm_click_handler() {\\n    if (is_downloading) {\\n        return;\\n    }\\n    dispatch(\\"click\\");\\n    if (href == null) {\\n        throw new Error(\\"href is not defined.\\");\\n    }\\n    if (worker_proxy == null) {\\n        throw new Error(\\"Wasm worker proxy is not available.\\");\\n    }\\n    const url = new URL(href, window.location.href);\\n    const path = url.pathname;\\n    is_downloading = true;\\n    worker_proxy.httpRequest({\\n        method: \\"GET\\",\\n        path,\\n        headers: {},\\n        query_string: \\"\\"\\n    }).then((response) => {\\n        if (response.status !== 200) {\\n            throw new Error(`Failed to get file ${path} from the Wasm worker.`);\\n        }\\n        const blob = new Blob([response.body], {\\n            type: getHeaderValue(response.headers, \\"content-type\\")\\n        });\\n        const blobUrl = URL.createObjectURL(blob);\\n        const link = document.createElement(\\"a\\");\\n        link.href = blobUrl;\\n        link.download = download;\\n        link.click();\\n        URL.revokeObjectURL(blobUrl);\\n    }).finally(() => {\\n        is_downloading = false;\\n    });\\n}\\n<\/script>\\n\\n{#if worker_proxy && should_proxy_wasm_src(href)}\\n\\t{#if is_downloading}\\n\\t\\t<slot />\\n\\t{:else}\\n\\t\\t<a {...$$restProps} {href} on:click|preventDefault={wasm_click_handler}>\\n\\t\\t\\t<slot />\\n\\t\\t</a>\\n\\t{/if}\\n{:else}\\n\\t<a\\n\\t\\tstyle:position=\\"relative\\"\\n\\t\\tclass=\\"download-link\\"\\n\\t\\t{href}\\n\\t\\ttarget={typeof window !== \\"undefined\\" && window.__is_colab__\\n\\t\\t\\t? \\"_blank\\"\\n\\t\\t\\t: null}\\n\\t\\trel=\\"noopener noreferrer\\"\\n\\t\\t{download}\\n\\t\\t{...$$restProps}\\n\\t\\ton:click={dispatch.bind(null, \\"click\\")}\\n\\t>\\n\\t\\t<slot />\\n\\t</a>\\n{/if}\\n\\n<style>\\n\\t.unstyled-link {\\n\\t\\tall: unset;\\n\\t\\tcursor: pointer;\\n\\t}</style>\\n"],"names":[],"mappings":"AAyEC,6BAAe,CACd,GAAG,CAAE,KAAK,CACV,MAAM,CAAE,OACT"}'},C=create_ssr_component((e,t,n,o)=>{let r=compute_rest_props(t,["href","download"]),{href:l=void 0}=t,{download:s}=t;createEventDispatcher();const u=f$1();return t.href===void 0&&n.href&&l!==void 0&&n.href(l),t.download===void 0&&n.download&&s!==void 0&&n.download(s),e.css.add(x$1),`${u&&w(l)?`${`<a${spread([escape_object(r),{href:escape_attribute_value(l)}],{classes:"svelte-1s8vnbx"})}>${o.default?o.default({}):""}</a>`}`:`<a${spread([{class:"download-link"},{href:escape_attribute_value(l)},{target:escape_attribute_value(typeof window<"u"&&window.__is_colab__?"_blank":null)},{rel:"noopener noreferrer"},{download:escape_attribute_value(s)},escape_object(r)],{classes:"svelte-1s8vnbx",styles:{position:"relative"}})}>${o.default?o.default({}):""}</a>`}`});

const d={code:"img.svelte-1pijsyv{object-fit:cover}",map:'{"version":3,"file":"Image.svelte","sources":["Image.svelte"],"sourcesContent":["<script lang=\\"ts\\">import { resolve_wasm_src } from \\"@gradio/wasm/svelte\\";\\nexport let src = void 0;\\nlet resolved_src;\\nlet latest_src;\\n$: {\\n    resolved_src = src;\\n    latest_src = src;\\n    const resolving_src = src;\\n    resolve_wasm_src(resolving_src).then((s) => {\\n        if (latest_src === resolving_src) {\\n            resolved_src = s;\\n        }\\n    });\\n}\\n<\/script>\\n\\n<!-- svelte-ignore a11y-missing-attribute -->\\n<img src={resolved_src} {...$$restProps} on:load />\\n\\n<style>\\n\\timg {\\n\\t\\tobject-fit: cover;\\n\\t}</style>\\n"],"names":[],"mappings":"AAoBC,kBAAI,CACH,UAAU,CAAE,KACb"}'},b=create_ssr_component((n,e,t,A$1)=>{let l=compute_rest_props(e,["src"]),{src:s=void 0}=e,r,c;e.src===void 0&&t.src&&s!==void 0&&t.src(s),n.css.add(d);{r=s,c=s;const o=s;A(o).then(i=>{c===o&&(r=i);});}return ` <img${spread([{src:escape_attribute_value(r)},escape_object(l)],{classes:"svelte-1pijsyv"})}>`});

const f={code:`button.svelte-1ixn6qd,a.svelte-1ixn6qd{display:inline-flex;justify-content:center;align-items:center;transition:var(--button-transition);padding:var(--size-0-5) var(--size-2);text-align:center}button.svelte-1ixn6qd:hover{transform:var(--button-transform-hover)}button.svelte-1ixn6qd:active,a.svelte-1ixn6qd:active{transform:var(--button-transform-active)}button[disabled].svelte-1ixn6qd,a.disabled.svelte-1ixn6qd{opacity:0.5;filter:grayscale(30%);cursor:not-allowed;transform:none}.hidden.svelte-1ixn6qd{display:none}.primary.svelte-1ixn6qd{border:var(--button-border-width) solid var(--button-primary-border-color);background:var(--button-primary-background-fill);color:var(--button-primary-text-color);box-shadow:var(--button-primary-shadow)}.primary.svelte-1ixn6qd:hover,.primary[disabled].svelte-1ixn6qd{background:var(--button-primary-background-fill-hover);color:var(--button-primary-text-color-hover)}.primary.svelte-1ixn6qd:hover{border-color:var(--button-primary-border-color-hover);box-shadow:var(--button-primary-shadow-hover)}.primary.svelte-1ixn6qd:active{box-shadow:var(--button-primary-shadow-active)}.primary[disabled].svelte-1ixn6qd{border-color:var(--button-primary-border-color)}.secondary.svelte-1ixn6qd{border:var(--button-border-width) solid
			var(--button-secondary-border-color);background:var(--button-secondary-background-fill);color:var(--button-secondary-text-color);box-shadow:var(--button-secondary-shadow)}.secondary.svelte-1ixn6qd:hover,.secondary[disabled].svelte-1ixn6qd{background:var(--button-secondary-background-fill-hover);color:var(--button-secondary-text-color-hover)}.secondary.svelte-1ixn6qd:hover{border-color:var(--button-secondary-border-color-hover);box-shadow:var(--button-secondary-shadow-hover)}.secondary.svelte-1ixn6qd:active{box-shadow:var(--button-secondary-shadow-active)}.secondary[disabled].svelte-1ixn6qd{border-color:var(--button-secondary-border-color)}.stop.svelte-1ixn6qd{background:var(--button-cancel-background-fill);color:var(--button-cancel-text-color);border:var(--button-border-width) solid var(--button-cancel-border-color);box-shadow:var(--button-secondary-shadow)}.stop.svelte-1ixn6qd:hover,.stop[disabled].svelte-1ixn6qd{background:var(--button-cancel-background-fill-hover)}.stop.svelte-1ixn6qd:hover{border-color:var(--button-cancel-border-color-hover);box-shadow:var(--button-secondary-shadow-hover)}.stop.svelte-1ixn6qd:active{box-shadow:var(--button-secondary-shadow-active)}.stop[disabled].svelte-1ixn6qd{border-color:var(--button-cancel-border-color)}.sm.svelte-1ixn6qd{border-radius:var(--button-small-radius);padding:var(--button-small-padding);font-weight:var(--button-small-text-weight);font-size:var(--button-small-text-size)}.md.svelte-1ixn6qd{border-radius:var(--button-medium-radius);padding:var(--button-medium-padding);font-weight:var(--button-medium-text-weight);font-size:var(--button-medium-text-size)}.lg.svelte-1ixn6qd{border-radius:var(--button-large-radius);padding:var(--button-large-padding);font-weight:var(--button-large-text-weight);font-size:var(--button-large-text-size)}.button-icon{width:var(--text-xl);height:var(--text-xl)}.button-icon.right-padded{margin-right:var(--spacing-md)}.huggingface.svelte-1ixn6qd{background:rgb(20, 28, 46);color:white}.huggingface.svelte-1ixn6qd:hover{background:rgb(40, 48, 66);color:white}`,map:'{"version":3,"file":"Button.svelte","sources":["Button.svelte"],"sourcesContent":["<script lang=\\"ts\\">import {} from \\"@gradio/client\\";\\nimport { Image } from \\"@gradio/image/shared\\";\\nexport let elem_id = \\"\\";\\nexport let elem_classes = [];\\nexport let visible = true;\\nexport let variant = \\"secondary\\";\\nexport let size = \\"lg\\";\\nexport let value = null;\\nexport let link = null;\\nexport let icon = null;\\nexport let disabled = false;\\nexport let scale = null;\\nexport let min_width = void 0;\\n<\/script>\\n\\n{#if link && link.length > 0}\\n\\t<a\\n\\t\\thref={link}\\n\\t\\trel=\\"noopener noreferrer\\"\\n\\t\\tclass:hidden={!visible}\\n\\t\\tclass:disabled\\n\\t\\taria-disabled={disabled}\\n\\t\\tclass=\\"{size} {variant} {elem_classes.join(\' \')}\\"\\n\\t\\tstyle:flex-grow={scale}\\n\\t\\tstyle:pointer-events={disabled ? \\"none\\" : null}\\n\\t\\tstyle:width={scale === 0 ? \\"fit-content\\" : null}\\n\\t\\tstyle:min-width={typeof min_width === \\"number\\"\\n\\t\\t\\t? `calc(min(${min_width}px, 100%))`\\n\\t\\t\\t: null}\\n\\t\\tid={elem_id}\\n\\t>\\n\\t\\t{#if icon}\\n\\t\\t\\t<Image class=\\"button-icon\\" src={icon.url} alt={`${value} icon`} />\\n\\t\\t{/if}\\n\\t\\t<slot />\\n\\t</a>\\n{:else}\\n\\t<button\\n\\t\\ton:click\\n\\t\\tclass:hidden={!visible}\\n\\t\\tclass=\\"{size} {variant} {elem_classes.join(\' \')}\\"\\n\\t\\tstyle:flex-grow={scale}\\n\\t\\tstyle:width={scale === 0 ? \\"fit-content\\" : null}\\n\\t\\tstyle:min-width={typeof min_width === \\"number\\"\\n\\t\\t\\t? `calc(min(${min_width}px, 100%))`\\n\\t\\t\\t: null}\\n\\t\\tid={elem_id}\\n\\t\\t{disabled}\\n\\t>\\n\\t\\t{#if icon}\\n\\t\\t\\t<Image\\n\\t\\t\\t\\tclass={`button-icon ${value ? \\"right-padded\\" : \\"\\"}`}\\n\\t\\t\\t\\tsrc={icon.url}\\n\\t\\t\\t\\talt={`${value} icon`}\\n\\t\\t\\t/>\\n\\t\\t{/if}\\n\\t\\t<slot />\\n\\t</button>\\n{/if}\\n\\n<style>\\n\\tbutton,\\n\\ta {\\n\\t\\tdisplay: inline-flex;\\n\\t\\tjustify-content: center;\\n\\t\\talign-items: center;\\n\\t\\ttransition: var(--button-transition);\\n\\t\\tpadding: var(--size-0-5) var(--size-2);\\n\\t\\ttext-align: center;\\n\\t}\\n\\n\\tbutton:hover {\\n\\t\\ttransform: var(--button-transform-hover);\\n\\t}\\n\\n\\tbutton:active,\\n\\ta:active {\\n\\t\\ttransform: var(--button-transform-active);\\n\\t}\\n\\n\\tbutton[disabled],\\n\\ta.disabled {\\n\\t\\topacity: 0.5;\\n\\t\\tfilter: grayscale(30%);\\n\\t\\tcursor: not-allowed;\\n\\t\\ttransform: none;\\n\\t}\\n\\n\\t.hidden {\\n\\t\\tdisplay: none;\\n\\t}\\n\\n\\t.primary {\\n\\t\\tborder: var(--button-border-width) solid var(--button-primary-border-color);\\n\\t\\tbackground: var(--button-primary-background-fill);\\n\\t\\tcolor: var(--button-primary-text-color);\\n\\t\\tbox-shadow: var(--button-primary-shadow);\\n\\t}\\n\\t.primary:hover,\\n\\t.primary[disabled] {\\n\\t\\tbackground: var(--button-primary-background-fill-hover);\\n\\t\\tcolor: var(--button-primary-text-color-hover);\\n\\t}\\n\\n\\t.primary:hover {\\n\\t\\tborder-color: var(--button-primary-border-color-hover);\\n\\t\\tbox-shadow: var(--button-primary-shadow-hover);\\n\\t}\\n\\t.primary:active {\\n\\t\\tbox-shadow: var(--button-primary-shadow-active);\\n\\t}\\n\\n\\t.primary[disabled] {\\n\\t\\tborder-color: var(--button-primary-border-color);\\n\\t}\\n\\n\\t.secondary {\\n\\t\\tborder: var(--button-border-width) solid\\n\\t\\t\\tvar(--button-secondary-border-color);\\n\\t\\tbackground: var(--button-secondary-background-fill);\\n\\t\\tcolor: var(--button-secondary-text-color);\\n\\t\\tbox-shadow: var(--button-secondary-shadow);\\n\\t}\\n\\n\\t.secondary:hover,\\n\\t.secondary[disabled] {\\n\\t\\tbackground: var(--button-secondary-background-fill-hover);\\n\\t\\tcolor: var(--button-secondary-text-color-hover);\\n\\t}\\n\\n\\t.secondary:hover {\\n\\t\\tborder-color: var(--button-secondary-border-color-hover);\\n\\t\\tbox-shadow: var(--button-secondary-shadow-hover);\\n\\t}\\n\\t.secondary:active {\\n\\t\\tbox-shadow: var(--button-secondary-shadow-active);\\n\\t}\\n\\n\\t.secondary[disabled] {\\n\\t\\tborder-color: var(--button-secondary-border-color);\\n\\t}\\n\\n\\t.stop {\\n\\t\\tbackground: var(--button-cancel-background-fill);\\n\\t\\tcolor: var(--button-cancel-text-color);\\n\\t\\tborder: var(--button-border-width) solid var(--button-cancel-border-color);\\n\\t\\tbox-shadow: var(--button-secondary-shadow);\\n\\t}\\n\\n\\t.stop:hover,\\n\\t.stop[disabled] {\\n\\t\\tbackground: var(--button-cancel-background-fill-hover);\\n\\t}\\n\\n\\t.stop:hover {\\n\\t\\tborder-color: var(--button-cancel-border-color-hover);\\n\\t\\tbox-shadow: var(--button-secondary-shadow-hover);\\n\\t}\\n\\t.stop:active {\\n\\t\\tbox-shadow: var(--button-secondary-shadow-active);\\n\\t}\\n\\n\\t.stop[disabled] {\\n\\t\\tborder-color: var(--button-cancel-border-color);\\n\\t}\\n\\n\\t.sm {\\n\\t\\tborder-radius: var(--button-small-radius);\\n\\t\\tpadding: var(--button-small-padding);\\n\\t\\tfont-weight: var(--button-small-text-weight);\\n\\t\\tfont-size: var(--button-small-text-size);\\n\\t}\\n\\n\\t.md {\\n\\t\\tborder-radius: var(--button-medium-radius);\\n\\t\\tpadding: var(--button-medium-padding);\\n\\t\\tfont-weight: var(--button-medium-text-weight);\\n\\t\\tfont-size: var(--button-medium-text-size);\\n\\t}\\n\\n\\t.lg {\\n\\t\\tborder-radius: var(--button-large-radius);\\n\\t\\tpadding: var(--button-large-padding);\\n\\t\\tfont-weight: var(--button-large-text-weight);\\n\\t\\tfont-size: var(--button-large-text-size);\\n\\t}\\n\\n\\t:global(.button-icon) {\\n\\t\\twidth: var(--text-xl);\\n\\t\\theight: var(--text-xl);\\n\\t}\\n\\t:global(.button-icon.right-padded) {\\n\\t\\tmargin-right: var(--spacing-md);\\n\\t}\\n\\n\\t.huggingface {\\n\\t\\tbackground: rgb(20, 28, 46);\\n\\t\\tcolor: white;\\n\\t}\\n\\n\\t.huggingface:hover {\\n\\t\\tbackground: rgb(40, 48, 66);\\n\\t\\tcolor: white;\\n\\t}</style>\\n"],"names":[],"mappings":"AA6DC,qBAAM,CACN,gBAAE,CACD,OAAO,CAAE,WAAW,CACpB,eAAe,CAAE,MAAM,CACvB,WAAW,CAAE,MAAM,CACnB,UAAU,CAAE,IAAI,mBAAmB,CAAC,CACpC,OAAO,CAAE,IAAI,UAAU,CAAC,CAAC,IAAI,QAAQ,CAAC,CACtC,UAAU,CAAE,MACb,CAEA,qBAAM,MAAO,CACZ,SAAS,CAAE,IAAI,wBAAwB,CACxC,CAEA,qBAAM,OAAO,CACb,gBAAC,OAAQ,CACR,SAAS,CAAE,IAAI,yBAAyB,CACzC,CAEA,MAAM,CAAC,QAAQ,gBAAC,CAChB,CAAC,wBAAU,CACV,OAAO,CAAE,GAAG,CACZ,MAAM,CAAE,UAAU,GAAG,CAAC,CACtB,MAAM,CAAE,WAAW,CACnB,SAAS,CAAE,IACZ,CAEA,sBAAQ,CACP,OAAO,CAAE,IACV,CAEA,uBAAS,CACR,MAAM,CAAE,IAAI,qBAAqB,CAAC,CAAC,KAAK,CAAC,IAAI,6BAA6B,CAAC,CAC3E,UAAU,CAAE,IAAI,gCAAgC,CAAC,CACjD,KAAK,CAAE,IAAI,2BAA2B,CAAC,CACvC,UAAU,CAAE,IAAI,uBAAuB,CACxC,CACA,uBAAQ,MAAM,CACd,QAAQ,CAAC,QAAQ,gBAAE,CAClB,UAAU,CAAE,IAAI,sCAAsC,CAAC,CACvD,KAAK,CAAE,IAAI,iCAAiC,CAC7C,CAEA,uBAAQ,MAAO,CACd,YAAY,CAAE,IAAI,mCAAmC,CAAC,CACtD,UAAU,CAAE,IAAI,6BAA6B,CAC9C,CACA,uBAAQ,OAAQ,CACf,UAAU,CAAE,IAAI,8BAA8B,CAC/C,CAEA,QAAQ,CAAC,QAAQ,gBAAE,CAClB,YAAY,CAAE,IAAI,6BAA6B,CAChD,CAEA,yBAAW,CACV,MAAM,CAAE,IAAI,qBAAqB,CAAC,CAAC;AACrC,GAAG,IAAI,+BAA+B,CAAC,CACrC,UAAU,CAAE,IAAI,kCAAkC,CAAC,CACnD,KAAK,CAAE,IAAI,6BAA6B,CAAC,CACzC,UAAU,CAAE,IAAI,yBAAyB,CAC1C,CAEA,yBAAU,MAAM,CAChB,UAAU,CAAC,QAAQ,gBAAE,CACpB,UAAU,CAAE,IAAI,wCAAwC,CAAC,CACzD,KAAK,CAAE,IAAI,mCAAmC,CAC/C,CAEA,yBAAU,MAAO,CAChB,YAAY,CAAE,IAAI,qCAAqC,CAAC,CACxD,UAAU,CAAE,IAAI,+BAA+B,CAChD,CACA,yBAAU,OAAQ,CACjB,UAAU,CAAE,IAAI,gCAAgC,CACjD,CAEA,UAAU,CAAC,QAAQ,gBAAE,CACpB,YAAY,CAAE,IAAI,+BAA+B,CAClD,CAEA,oBAAM,CACL,UAAU,CAAE,IAAI,+BAA+B,CAAC,CAChD,KAAK,CAAE,IAAI,0BAA0B,CAAC,CACtC,MAAM,CAAE,IAAI,qBAAqB,CAAC,CAAC,KAAK,CAAC,IAAI,4BAA4B,CAAC,CAC1E,UAAU,CAAE,IAAI,yBAAyB,CAC1C,CAEA,oBAAK,MAAM,CACX,KAAK,CAAC,QAAQ,gBAAE,CACf,UAAU,CAAE,IAAI,qCAAqC,CACtD,CAEA,oBAAK,MAAO,CACX,YAAY,CAAE,IAAI,kCAAkC,CAAC,CACrD,UAAU,CAAE,IAAI,+BAA+B,CAChD,CACA,oBAAK,OAAQ,CACZ,UAAU,CAAE,IAAI,gCAAgC,CACjD,CAEA,KAAK,CAAC,QAAQ,gBAAE,CACf,YAAY,CAAE,IAAI,4BAA4B,CAC/C,CAEA,kBAAI,CACH,aAAa,CAAE,IAAI,qBAAqB,CAAC,CACzC,OAAO,CAAE,IAAI,sBAAsB,CAAC,CACpC,WAAW,CAAE,IAAI,0BAA0B,CAAC,CAC5C,SAAS,CAAE,IAAI,wBAAwB,CACxC,CAEA,kBAAI,CACH,aAAa,CAAE,IAAI,sBAAsB,CAAC,CAC1C,OAAO,CAAE,IAAI,uBAAuB,CAAC,CACrC,WAAW,CAAE,IAAI,2BAA2B,CAAC,CAC7C,SAAS,CAAE,IAAI,yBAAyB,CACzC,CAEA,kBAAI,CACH,aAAa,CAAE,IAAI,qBAAqB,CAAC,CACzC,OAAO,CAAE,IAAI,sBAAsB,CAAC,CACpC,WAAW,CAAE,IAAI,0BAA0B,CAAC,CAC5C,SAAS,CAAE,IAAI,wBAAwB,CACxC,CAEQ,YAAc,CACrB,KAAK,CAAE,IAAI,SAAS,CAAC,CACrB,MAAM,CAAE,IAAI,SAAS,CACtB,CACQ,yBAA2B,CAClC,YAAY,CAAE,IAAI,YAAY,CAC/B,CAEA,2BAAa,CACZ,UAAU,CAAE,IAAI,EAAE,CAAC,CAAC,EAAE,CAAC,CAAC,EAAE,CAAC,CAC3B,KAAK,CAAE,KACR,CAEA,2BAAY,MAAO,CAClB,UAAU,CAAE,IAAI,EAAE,CAAC,CAAC,EAAE,CAAC,CAAC,EAAE,CAAC,CAC3B,KAAK,CAAE,KACR"}'},E=create_ssr_component((u,t,A,b$1)=>{let{elem_id:i=""}=t,{elem_classes:d=[]}=t,{visible:v=!0}=t,{variant:a="secondary"}=t,{size:c="lg"}=t,{value:C=null}=t,{link:l=null}=t,{icon:e=null}=t,{disabled:o=!1}=t,{scale:n=null}=t,{min_width:r=void 0}=t;return t.elem_id===void 0&&A.elem_id&&i!==void 0&&A.elem_id(i),t.elem_classes===void 0&&A.elem_classes&&d!==void 0&&A.elem_classes(d),t.visible===void 0&&A.visible&&v!==void 0&&A.visible(v),t.variant===void 0&&A.variant&&a!==void 0&&A.variant(a),t.size===void 0&&A.size&&c!==void 0&&A.size(c),t.value===void 0&&A.value&&C!==void 0&&A.value(C),t.link===void 0&&A.link&&l!==void 0&&A.link(l),t.icon===void 0&&A.icon&&e!==void 0&&A.icon(e),t.disabled===void 0&&A.disabled&&o!==void 0&&A.disabled(o),t.scale===void 0&&A.scale&&n!==void 0&&A.scale(n),t.min_width===void 0&&A.min_width&&r!==void 0&&A.min_width(r),u.css.add(f),`${l&&l.length>0?`<a${add_attribute("href",l,0)} rel="noopener noreferrer"${add_attribute("aria-disabled",o,0)} class="${[escape(c,!0)+" "+escape(a,!0)+" "+escape(d.join(" "),!0)+" svelte-1ixn6qd",(v?"":"hidden")+" "+(o?"disabled":"")].join(" ").trim()}"${add_attribute("id",i,0)}${add_styles({"flex-grow":n,"pointer-events":o?"none":null,width:n===0?"fit-content":null,"min-width":typeof r=="number"?`calc(min(${r}px, 100%))`:null})}>${e?`${validate_component(b,"Image").$$render(u,{class:"button-icon",src:e.url,alt:`${C} icon`},{},{})}`:""} ${b$1.default?b$1.default({}):""}</a>`:`<button class="${[escape(c,!0)+" "+escape(a,!0)+" "+escape(d.join(" "),!0)+" svelte-1ixn6qd",v?"":"hidden"].join(" ").trim()}"${add_attribute("id",i,0)} ${o?"disabled":""}${add_styles({"flex-grow":n,width:n===0?"fit-content":null,"min-width":typeof r=="number"?`calc(min(${r}px, 100%))`:null})}>${e?`${validate_component(b,"Image").$$render(u,{class:`button-icon ${C?"right-padded":""}`,src:e.url,alt:`${C} icon`},{},{})}`:""} ${b$1.default?b$1.default({}):""}</button>`}`}),k=create_ssr_component((u,t,A,b)=>{let{elem_id:i=""}=t,{elem_classes:d=[]}=t,{visible:v=!0}=t,{value:a}=t,{variant:c="secondary"}=t,{interactive:C}=t,{size:l="lg"}=t,{scale:e=null}=t,{icon:o=null}=t,{link:n=null}=t,{min_width:r=void 0}=t,{gradio:B}=t;return t.elem_id===void 0&&A.elem_id&&i!==void 0&&A.elem_id(i),t.elem_classes===void 0&&A.elem_classes&&d!==void 0&&A.elem_classes(d),t.visible===void 0&&A.visible&&v!==void 0&&A.visible(v),t.value===void 0&&A.value&&a!==void 0&&A.value(a),t.variant===void 0&&A.variant&&c!==void 0&&A.variant(c),t.interactive===void 0&&A.interactive&&C!==void 0&&A.interactive(C),t.size===void 0&&A.size&&l!==void 0&&A.size(l),t.scale===void 0&&A.scale&&e!==void 0&&A.scale(e),t.icon===void 0&&A.icon&&o!==void 0&&A.icon(o),t.link===void 0&&A.link&&n!==void 0&&A.link(n),t.min_width===void 0&&A.min_width&&r!==void 0&&A.min_width(r),t.gradio===void 0&&A.gradio&&B!==void 0&&A.gradio(B),`${validate_component(E,"Button").$$render(u,{value:a,variant:c,elem_id:i,elem_classes:d,size:l,scale:e,link:n,icon:o,min_width:r,visible:v,disabled:!C},{},{default:()=>`${escape(a??"")}`})}`});

var Index34 = /*#__PURE__*/Object.freeze({
	__proto__: null,
	BaseButton: E,
	default: k
});

const x={code:"div.svelte-bnzux8{display:flex;position:relative;flex-direction:column;gap:var(--layout-gap)}div.svelte-bnzux8>*,div.svelte-bnzux8>.form > *{width:var(--size-full)}.hide.svelte-bnzux8{display:none}.compact.svelte-bnzux8>*,.compact.svelte-bnzux8 .box{border-radius:0}.compact.svelte-bnzux8,.panel.svelte-bnzux8{border:solid var(--panel-border-width) var(--panel-border-color);border-radius:var(--container-radius);background:var(--panel-background-fill);padding:var(--spacing-lg)}",map:`{"version":3,"file":"Index.svelte","sources":["Index.svelte"],"sourcesContent":["<script lang=\\"ts\\">import { StatusTracker } from \\"@gradio/statustracker\\";\\nexport let scale = null;\\nexport let min_width = 0;\\nexport let elem_id = \\"\\";\\nexport let elem_classes = [];\\nexport let visible = true;\\nexport let variant = \\"default\\";\\nexport let loading_status = void 0;\\nexport let gradio = void 0;\\nexport let show_progress = false;\\n<\/script>\\n\\n<div\\n\\tid={elem_id}\\n\\tclass=\\"column {elem_classes.join(' ')}\\"\\n\\tclass:compact={variant === \\"compact\\"}\\n\\tclass:panel={variant === \\"panel\\"}\\n\\tclass:hide={!visible}\\n\\tstyle:flex-grow={scale}\\n\\tstyle:min-width=\\"calc(min({min_width}px, 100%))\\"\\n>\\n\\t{#if loading_status && show_progress && gradio}\\n\\t\\t<StatusTracker\\n\\t\\t\\tautoscroll={gradio.autoscroll}\\n\\t\\t\\ti18n={gradio.i18n}\\n\\t\\t\\t{...loading_status}\\n\\t\\t\\tstatus={loading_status\\n\\t\\t\\t\\t? loading_status.status == \\"pending\\"\\n\\t\\t\\t\\t\\t? \\"generating\\"\\n\\t\\t\\t\\t\\t: loading_status.status\\n\\t\\t\\t\\t: null}\\n\\t\\t/>\\n\\t{/if}\\n\\t<slot />\\n</div>\\n\\n<style>\\n\\tdiv {\\n\\t\\tdisplay: flex;\\n\\t\\tposition: relative;\\n\\t\\tflex-direction: column;\\n\\t\\tgap: var(--layout-gap);\\n\\t}\\n\\n\\tdiv > :global(*),\\n\\tdiv > :global(.form > *) {\\n\\t\\twidth: var(--size-full);\\n\\t}\\n\\n\\t.hide {\\n\\t\\tdisplay: none;\\n\\t}\\n\\n\\t.compact > :global(*),\\n\\t.compact :global(.box) {\\n\\t\\tborder-radius: 0;\\n\\t}\\n\\n\\t.compact,\\n\\t.panel {\\n\\t\\tborder: solid var(--panel-border-width) var(--panel-border-color);\\n\\t\\tborder-radius: var(--container-radius);\\n\\t\\tbackground: var(--panel-background-fill);\\n\\t\\tpadding: var(--spacing-lg);\\n\\t}</style>\\n"],"names":[],"mappings":"AAqCC,iBAAI,CACH,OAAO,CAAE,IAAI,CACb,QAAQ,CAAE,QAAQ,CAClB,cAAc,CAAE,MAAM,CACtB,GAAG,CAAE,IAAI,YAAY,CACtB,CAEA,iBAAG,CAAW,CAAE,CAChB,iBAAG,CAAW,SAAW,CACxB,KAAK,CAAE,IAAI,WAAW,CACvB,CAEA,mBAAM,CACL,OAAO,CAAE,IACV,CAEA,sBAAQ,CAAW,CAAE,CACrB,sBAAQ,CAAS,IAAM,CACtB,aAAa,CAAE,CAChB,CAEA,sBAAQ,CACR,oBAAO,CACN,MAAM,CAAE,KAAK,CAAC,IAAI,oBAAoB,CAAC,CAAC,IAAI,oBAAoB,CAAC,CACjE,aAAa,CAAE,IAAI,kBAAkB,CAAC,CACtC,UAAU,CAAE,IAAI,uBAAuB,CAAC,CACxC,OAAO,CAAE,IAAI,YAAY,CAC1B"}`},h=create_ssr_component((c,t,e,v)=>{let{scale:i=null}=t,{min_width:n=0}=t,{elem_id:o=""}=t,{elem_classes:s=[]}=t,{visible:r=!0}=t,{variant:A="default"}=t,{loading_status:a=void 0}=t,{gradio:l=void 0}=t,{show_progress:d=!1}=t;return t.scale===void 0&&e.scale&&i!==void 0&&e.scale(i),t.min_width===void 0&&e.min_width&&n!==void 0&&e.min_width(n),t.elem_id===void 0&&e.elem_id&&o!==void 0&&e.elem_id(o),t.elem_classes===void 0&&e.elem_classes&&s!==void 0&&e.elem_classes(s),t.visible===void 0&&e.visible&&r!==void 0&&e.visible(r),t.variant===void 0&&e.variant&&A!==void 0&&e.variant(A),t.loading_status===void 0&&e.loading_status&&a!==void 0&&e.loading_status(a),t.gradio===void 0&&e.gradio&&l!==void 0&&e.gradio(l),t.show_progress===void 0&&e.show_progress&&d!==void 0&&e.show_progress(d),c.css.add(x),`<div${add_attribute("id",o,0)} class="${["column "+escape(s.join(" "),!0)+" svelte-bnzux8",(A==="compact"?"compact":"")+" "+(A==="panel"?"panel":"")+" "+(r?"":"hide")].join(" ").trim()}"${add_styles({"flex-grow":i,"min-width":`calc(min(${n}px, 100%))`})}>${a&&d&&l?`${validate_component(Et,"StatusTracker").$$render(c,Object.assign({},{autoscroll:l.autoscroll},{i18n:l.i18n},a,{status:a?a.status=="pending"?"generating":a.status:null}),{},{})}`:""} ${v.default?v.default({}):""} </div>`});

var Index19 = /*#__PURE__*/Object.freeze({
	__proto__: null,
	default: h
});

const{Object:Xt}=globals,$t=create_ssr_component((a,e,t,H)=>{let r=compute_rest_props(e,["root","component","target","theme_mode","instance","value","elem_id","elem_classes","_id","visible"]),{root:b}=e,{component:p}=e,{target:n}=e,{theme_mode:E}=e,{instance:v}=e,{value:u}=e,{elem_id:y}=e,{elem_classes:l}=e,{_id:I}=e,{visible:x}=e;const O=(S,L,Z)=>new CustomEvent("prop_change",{detail:{id:S,prop:L,value:Z}});function T(S){return new Proxy(S,{construct(Z,ie){const J=new Z(...ie),h=Object.keys(J.$$.props);function X(K){return function(ue){if(!n)return;const ae=O(I,K,ue);n.dispatchEvent(ae);}}return h.forEach(K=>{binding_callbacks.push(()=>bind(J,K,X(K)));}),J}})}let G=T(p);const q=["description","info","title","placeholder","value","label"];function g(S){for(const L in S)q.includes(L)&&(S[L]=ra(S[L]));}e.root===void 0&&t.root&&b!==void 0&&t.root(b),e.component===void 0&&t.component&&p!==void 0&&t.component(p),e.target===void 0&&t.target&&n!==void 0&&t.target(n),e.theme_mode===void 0&&t.theme_mode&&E!==void 0&&t.theme_mode(E),e.instance===void 0&&t.instance&&v!==void 0&&t.instance(v),e.value===void 0&&t.value&&u!==void 0&&t.value(u),e.elem_id===void 0&&t.elem_id&&y!==void 0&&t.elem_id(y),e.elem_classes===void 0&&t.elem_classes&&l!==void 0&&t.elem_classes(l),e._id===void 0&&t._id&&I!==void 0&&t._id(I),e.visible===void 0&&t.visible&&x!==void 0&&t.visible(x);let A,Q,se=a.head;do A=!0,a.head=se,g(r),u=ra(u),Q=`  ${x?`${validate_component(G||missing_component,"svelte:component").$$render(a,Xt.assign({},{elem_id:y},{elem_classes:l},{target:n},{visible:x},r,{theme_mode:E},{root:b},{this:v},{value:u}),{this:S=>{v=S,A=!1;},value:S=>{u=S,A=!1;}},{default:()=>`${H.default?H.default({}):""}`})}`:""}`;while(!A);return Q}),lt=create_ssr_component((a,e,t,H)=>{let r,b;b=subscribe(ta,A=>r=A);let{root:p}=e,{node:n}=e,{parent:E=null}=e,{target:v}=e,{theme_mode:u}=e,{version:y}=e,{autoscroll:l}=e,{max_file_size:I}=e,{client:x}=e;createEventDispatcher();setContext("BLOCK_KEY",E),e.root===void 0&&t.root&&p!==void 0&&t.root(p),e.node===void 0&&t.node&&n!==void 0&&t.node(n),e.parent===void 0&&t.parent&&E!==void 0&&t.parent(E),e.target===void 0&&t.target&&v!==void 0&&t.target(v),e.theme_mode===void 0&&t.theme_mode&&u!==void 0&&t.theme_mode(u),e.version===void 0&&t.version&&y!==void 0&&t.version(y),e.autoscroll===void 0&&t.autoscroll&&l!==void 0&&t.autoscroll(l),e.max_file_size===void 0&&t.max_file_size&&I!==void 0&&t.max_file_size(I),e.client===void 0&&t.client&&x!==void 0&&t.client(x);let G,q,g=a.head;do G=!0,a.head=g,n&&(n.children=n.children&&n.children.filter(A=>{const Q=n.type!=="statustracker";return Q})),n&&n.type==="form"&&(n.children?.every(A=>typeof A.props.visible=="boolean"&&!A.props.visible)?n.props.visible=!1:n.props.visible=!0),n.props.gradio=new m$1(n.id,v,u,y,p,l,I,r,x,Kt$2),q=`${n.component?`${validate_component($t,"RenderComponent").$$render(a,Object.assign({},{_id:n?.id},{component:n.component},{elem_id:"elem_id"in n.props&&n.props.elem_id||`component-${n.id}`},{elem_classes:"elem_classes"in n.props&&n.props.elem_classes||[]},{target:v},n.props,{theme_mode:u},{root:p},{visible:typeof n.props.visible=="boolean"?n.props.visible:!0},{instance:n.instance},{value:n.props.value}),{instance:A=>{n.instance=A,G=!1;},value:A=>{n.props.value=A,G=!1;}},{default:()=>`${n.children&&n.children.length?`${each(n.children,A=>`${validate_component(lt,"svelte:self").$$render(a,{node:A,component:A.component,target:v,id:A.id,root:p,theme_mode:u,max_file_size:I,client:x},{},{})}`)}`:""}`})}`:""}`;while(!G);return b(),q}),en=create_ssr_component((a,e,t,H)=>{let{rootNode:r}=e,{root:b}=e,{target:p}=e,{theme_mode:n}=e,{version:E}=e,{autoscroll:v}=e,{max_file_size:u=null}=e,{client:y}=e;createEventDispatcher();return e.rootNode===void 0&&t.rootNode&&r!==void 0&&t.rootNode(r),e.root===void 0&&t.root&&b!==void 0&&t.root(b),e.target===void 0&&t.target&&p!==void 0&&t.target(p),e.theme_mode===void 0&&t.theme_mode&&n!==void 0&&t.theme_mode(n),e.version===void 0&&t.version&&E!==void 0&&t.version(E),e.autoscroll===void 0&&t.autoscroll&&v!==void 0&&t.autoscroll(v),e.max_file_size===void 0&&t.max_file_size&&u!==void 0&&t.max_file_size(u),e.client===void 0&&t.client&&y!==void 0&&t.client(y),`${r?`${validate_component(lt,"Render").$$render(a,{node:r,root:b,target:p,theme_mode:n,version:E,autoscroll:v,max_file_size:u,client:y},{},{})}`:""}`}),tn="data:image/svg+xml,%3csvg%20xmlns='http://www.w3.org/2000/svg'%20width='576'%20height='576'%20viewBox='0%200%20576%20576'%20fill='none'%3e%3cpath%20d='M287.5%20229L86%20344.5L287.5%20460L489%20344.5L287.5%20229Z'%20stroke='url(%23paint0_linear_102_7)'%20stroke-width='59'%20stroke-linejoin='round'/%3e%3cpath%20d='M287.5%20116L86%20231.5L287.5%20347L489%20231.5L287.5%20116Z'%20stroke='url(%23paint1_linear_102_7)'%20stroke-width='59'%20stroke-linejoin='round'/%3e%3cpath%20d='M86%20344L288%20229'%20stroke='url(%23paint2_linear_102_7)'%20stroke-width='59'%20stroke-linejoin='bevel'/%3e%3cdefs%3e%3clinearGradient%20id='paint0_linear_102_7'%20x1='60'%20y1='341'%20x2='429.5'%20y2='344'%20gradientUnits='userSpaceOnUse'%3e%3cstop%20stop-color='%23F9D100'/%3e%3cstop%20offset='1'%20stop-color='%23F97700'/%3e%3c/linearGradient%3e%3clinearGradient%20id='paint1_linear_102_7'%20x1='513.5'%20y1='231'%20x2='143.5'%20y2='231'%20gradientUnits='userSpaceOnUse'%3e%3cstop%20stop-color='%23F9D100'/%3e%3cstop%20offset='1'%20stop-color='%23F97700'/%3e%3c/linearGradient%3e%3clinearGradient%20id='paint2_linear_102_7'%20x1='60'%20y1='344'%20x2='428.987'%20y2='341.811'%20gradientUnits='userSpaceOnUse'%3e%3cstop%20stop-color='%23F9D100'/%3e%3cstop%20offset='1'%20stop-color='%23F97700'/%3e%3c/linearGradient%3e%3c/defs%3e%3c/svg%3e",nn="data:image/svg+xml,%3csvg%20width='28'%20height='28'%20viewBox='0%200%2028%2028'%20fill='none'%20xmlns='http://www.w3.org/2000/svg'%3e%3cpath%20fill-rule='evenodd'%20clip-rule='evenodd'%20d='M26.9425%202.94265C27.4632%202.42195%2027.4632%201.57773%2026.9425%201.05703C26.4218%200.536329%2025.5776%200.536329%2025.0569%201.05703L22.5713%203.54256C21.1213%202.59333%2019.5367%202.43378%2018.1753%202.64006C16.5495%202.88638%2015.1127%203.66838%2014.3905%204.39053L12.3905%206.39053C12.1405%206.64058%2012%206.97972%2012%207.33334C12%207.68697%2012.1405%208.0261%2012.3905%208.27615L19.7239%2015.6095C20.2446%2016.1302%2021.0888%2016.1302%2021.6095%2015.6095L23.6095%2013.6095C24.3316%2012.8873%2025.1136%2011.4505%2025.36%209.82475C25.5663%208.46312%2025.4066%206.87827%2024.4571%205.42807L26.9425%202.94265Z'%20fill='%233c4555'/%3e%3cpath%20fill-rule='evenodd'%20clip-rule='evenodd'%20d='M12.276%2012.9426C12.7967%2012.4219%2012.7967%2011.5777%2012.276%2011.057C11.7553%2010.5363%2010.9111%2010.5363%2010.3904%2011.057L8.66651%2012.7809L8.27615%2012.3905C8.0261%2012.1405%207.68697%2012%207.33334%2012C6.97972%2012%206.64058%2012.1405%206.39053%2012.3905L4.39053%2014.3905C3.66838%2015.1127%202.88638%2016.5495%202.64006%2018.1753C2.43377%2019.5367%202.59333%2021.1214%203.54262%2022.5714L1.05703%2025.057C0.536329%2025.5777%200.536329%2026.4219%201.05703%2026.9426C1.57773%2027.4633%202.42195%2027.4633%202.94265%2026.9426L5.42817%2024.4571C6.87835%2025.4066%208.46315%2025.5663%209.82475%2025.36C11.4505%2025.1136%2012.8873%2024.3316%2013.6095%2023.6095L15.6095%2021.6095C16.1302%2021.0888%2016.1302%2020.2446%2015.6095%2019.7239L15.2188%2019.3332L16.9426%2017.6093C17.4633%2017.0886%2017.4633%2016.2444%2016.9426%2015.7237C16.4219%2015.203%2015.5777%2015.203%2015.057%2015.7237L13.3332%2017.4475L10.5521%2014.6665L12.276%2012.9426Z'%20fill='%23FF7C00'/%3e%3c/svg%3e",on="data:image/svg+xml,%3csvg%20width='24'%20height='24'%20viewBox='0%200%2024%2024'%20xmlns='http://www.w3.org/2000/svg'%3e%3c!--%20Outer%20gear%20teeth%20(gray)%20--%3e%3cpath%20d='M19.14%2012.94c.04-.3.06-.61.06-.94%200-.32-.02-.64-.07-.94l2.03-1.58c.18-.14.23-.41.12-.61l-1.92-3.32c-.12-.22-.37-.29-.59-.22l-2.39.96c-.5-.38-1.03-.7-1.62-.94l-.36-2.54c-.04-.24-.24-.41-.48-.41h-3.84c-.24%200-.43.17-.47.41l-.36%202.54c-.59.24-1.13.57-1.62.94l-2.39-.96c-.22-.08-.47%200-.59.22L2.74%208.87c-.12.21-.08.47.12.61l2.03%201.58c-.05.3-.07.62-.07.94s.02.64.07.94l-2.03%201.58c-.18.14-.23.41-.12.61l1.92%203.32c.12.22.37.29.59.22l2.39-.96c.5.38%201.03.7%201.62.94l.36%202.54c.05.24.24.41.48.41h3.84c.24%200%20.44-.17.47-.41l.36-2.54c.59-.24%201.13-.56%201.62-.94l2.39.96c.22.08.47%200%20.59-.22l1.92-3.32c.12-.22.07-.47-.12-.61l-2.01-1.58zM12%2015.6c-1.98%200-3.6-1.62-3.6-3.6s1.62-3.6%203.6-3.6%203.6%201.62%203.6%203.6-1.62%203.6-3.6%203.6z'%20fill='%23808080'/%3e%3c!--%20Inner%20circle%20(now%20gray)%20--%3e%3ccircle%20cx='12'%20cy='12'%20r='2.5'%20fill='%23808080'/%3e%3c/svg%3e",sn="data:image/svg+xml,%3csvg%20viewBox='0%200%2020%2020'%20version='1.1'%20xmlns='http://www.w3.org/2000/svg'%20xmlns:xlink='http://www.w3.org/1999/xlink'%20fill='%23000000'%3e%3cg%20id='SVGRepo_bgCarrier'%20stroke-width='0'%3e%3c/g%3e%3cg%20id='SVGRepo_tracerCarrier'%20stroke-linecap='round'%20stroke-linejoin='round'%3e%3c/g%3e%3cg%20id='SVGRepo_iconCarrier'%3e%3ctitle%3erecord%20[%23982]%3c/title%3e%3cdesc%3eCreated%20with%20Sketch.%3c/desc%3e%3cdefs%3e%3c/defs%3e%3cg%20id='Page-1'%20stroke='none'%20stroke-width='1'%20fill='none'%20fill-rule='evenodd'%3e%3cg%20id='Dribbble-Light-Preview'%20transform='translate(-380.000000,%20-3839.000000)'%20fill='%23FF0000'%3e%3cg%20id='icons'%20transform='translate(56.000000,%20160.000000)'%3e%3cpath%20d='M338,3689%20C338,3691.209%20336.209,3693%20334,3693%20C331.791,3693%20330,3691.209%20330,3689%20C330,3686.791%20331.791,3685%20334,3685%20C336.209,3685%20338,3686.791%20338,3689%20M334,3697%20C329.589,3697%20326,3693.411%20326,3689%20C326,3684.589%20329.589,3681%20334,3681%20C338.411,3681%20342,3684.589%20342,3689%20C342,3693.411%20338.411,3697%20334,3697%20M334,3679%20C328.477,3679%20324,3683.477%20324,3689%20C324,3694.523%20328.477,3699%20334,3699%20C339.523,3699%20344,3694.523%20344,3689%20C344,3683.477%20339.523,3679%20334,3679'%20id='record-[%23982]'%3e%3c/path%3e%3c/g%3e%3c/g%3e%3c/g%3e%3c/g%3e%3c/svg%3e";const an={code:".wrap.svelte-czcr5b.svelte-czcr5b{display:flex;flex-grow:1;flex-direction:column;width:var(--size-full);font-weight:var(--body-text-weight);font-size:var(--body-text-size)}.contain.svelte-czcr5b.svelte-czcr5b{display:flex;flex-direction:column}footer.svelte-czcr5b.svelte-czcr5b{display:flex;justify-content:center;margin-top:var(--size-4);color:var(--body-text-color-subdued)}.divider.svelte-czcr5b.svelte-czcr5b{margin-left:var(--size-1);margin-right:var(--size-2)}.show-api.svelte-czcr5b.svelte-czcr5b,.settings.svelte-czcr5b.svelte-czcr5b,.record.svelte-czcr5b.svelte-czcr5b{display:flex;align-items:center}.show-api.svelte-czcr5b.svelte-czcr5b:hover{color:var(--body-text-color)}.show-api.svelte-czcr5b img.svelte-czcr5b{margin-right:var(--size-1);margin-left:var(--size-2);width:var(--size-3)}.settings.svelte-czcr5b img.svelte-czcr5b{margin-right:var(--size-1);margin-left:var(--size-1);width:var(--size-4)}.record.svelte-czcr5b img.svelte-czcr5b{margin-right:var(--size-1);margin-left:var(--size-1);width:var(--size-3)}.built-with.svelte-czcr5b.svelte-czcr5b{display:flex;align-items:center}.built-with.svelte-czcr5b.svelte-czcr5b:hover,.settings.svelte-czcr5b.svelte-czcr5b:hover,.record.svelte-czcr5b.svelte-czcr5b:hover{color:var(--body-text-color)}.built-with.svelte-czcr5b img.svelte-czcr5b{margin-right:var(--size-1);margin-left:var(--size-1);margin-bottom:1px;width:var(--size-4)}.api-docs.svelte-czcr5b.svelte-czcr5b{display:flex;position:fixed;top:0;right:0;z-index:var(--layer-top);background:rgba(0, 0, 0, 0.5);width:var(--size-screen);height:var(--size-screen-h)}.backdrop.svelte-czcr5b.svelte-czcr5b{flex:1 1 0%;-webkit-backdrop-filter:blur(4px);backdrop-filter:blur(4px)}.api-docs-wrap.svelte-czcr5b.svelte-czcr5b{box-shadow:var(--shadow-drop-lg);background:var(--background-fill-primary);overflow-x:hidden;overflow-y:auto}@media(min-width: 768px){.api-docs-wrap.svelte-czcr5b.svelte-czcr5b{border-top-left-radius:var(--radius-lg);border-bottom-left-radius:var(--radius-lg);width:950px}}@media(min-width: 1536px){.api-docs-wrap.svelte-czcr5b.svelte-czcr5b{width:1150px}}#api-recorder-container.svelte-czcr5b.svelte-czcr5b{position:fixed;left:10px;bottom:10px;z-index:1000}.show-api.svelte-czcr5b.svelte-czcr5b{display:flex;align-items:center}@media(max-width: 640px){.show-api.svelte-czcr5b.svelte-czcr5b,.show-api-divider.svelte-czcr5b.svelte-czcr5b{display:none}}.show-api.svelte-czcr5b.svelte-czcr5b:hover{color:var(--body-text-color)}.hidden.svelte-czcr5b.svelte-czcr5b{display:none}",map:'{"version":3,"file":"Blocks.svelte","sources":["Blocks.svelte"],"sourcesContent":["<script lang=\\"ts\\">import { tick, onMount } from \\"svelte\\";\\nimport { _ } from \\"svelte-i18n\\";\\nimport { Client } from \\"@gradio/client\\";\\nimport { writable } from \\"svelte/store\\";\\nimport { setupi18n } from \\"./i18n\\";\\nimport { Toast } from \\"@gradio/statustracker\\";\\nimport MountComponents from \\"./MountComponents.svelte\\";\\nimport { prefix_css } from \\"./css\\";\\nimport logo from \\"./images/logo.svg\\";\\nimport api_logo from \\"./api_docs/img/api-logo.svg\\";\\nimport settings_logo from \\"./api_docs/img/settings-logo.svg\\";\\nimport record_stop from \\"./api_docs/img/record-stop.svg\\";\\nimport { create_components, AsyncFunction } from \\"./init\\";\\nimport * as screen_recorder from \\"./screen_recorder\\";\\nexport let root;\\nexport let components;\\nexport let layout;\\nexport let dependencies;\\nexport let title = \\"Gradio\\";\\nexport let target;\\nexport let autoscroll;\\nexport let show_api = true;\\nexport let show_footer = true;\\nexport let control_page_title = false;\\nexport let app_mode;\\nexport let theme_mode;\\nexport let app;\\nexport let space_id;\\nexport let version;\\nexport let js;\\nexport let fill_height = false;\\nexport let ready;\\nexport let username;\\nexport let api_prefix = \\"\\";\\nexport let max_file_size = void 0;\\nexport let initial_layout = void 0;\\nexport let css = null;\\nexport let vibe_mode = false;\\nlet broken_connection = false;\\nlet { layout: _layout, targets, update_value, get_data, modify_stream, get_stream_state, set_time_limit, loading_status, scheduled_updates, create_layout, rerender_layout, value_change } = create_components({\\n    initial_layout\\n});\\n$: components, layout, dependencies, root, app, fill_height, target, run();\\n$: {\\n    ready = !!$_layout;\\n}\\nlet old_dependencies = dependencies;\\n$: if (dependencies !== old_dependencies && render_complete && !layout_creating) {\\n    handle_load_triggers();\\n    old_dependencies = dependencies;\\n}\\nlet vibe_editor_width = 350;\\nasync function run() {\\n    await setupi18n(app.config?.i18n_translations || void 0);\\n    layout_creating = true;\\n    await create_layout({\\n        components,\\n        layout,\\n        dependencies,\\n        root: root + api_prefix,\\n        app,\\n        options: {\\n            fill_height\\n        }\\n    });\\n    layout_creating = false;\\n}\\nexport let search_params;\\nlet api_docs_visible = search_params.get(\\"view\\") === \\"api\\" && show_api;\\nlet settings_visible = search_params.get(\\"view\\") === \\"settings\\";\\nlet api_recorder_visible = search_params.get(\\"view\\") === \\"api-recorder\\" && show_api;\\nlet allow_zoom = true;\\nlet allow_video_trim = true;\\nlet ApiDocs = null;\\nlet ApiRecorder = null;\\nlet Settings = null;\\nlet VibeEditor = null;\\nasync function loadApiDocs() {\\n    if (!ApiDocs || !ApiRecorder) {\\n        const api_docs_module = await import(\\"./api_docs/ApiDocs.svelte\\");\\n        const api_recorder_module = await import(\\"./api_docs/ApiRecorder.svelte\\");\\n        if (!ApiDocs)\\n            ApiDocs = api_docs_module.default;\\n        if (!ApiRecorder)\\n            ApiRecorder = api_recorder_module.default;\\n    }\\n}\\nasync function loadApiRecorder() {\\n    if (!ApiRecorder) {\\n        const api_recorder_module = await import(\\"./api_docs/ApiRecorder.svelte\\");\\n        ApiRecorder = api_recorder_module.default;\\n    }\\n}\\nasync function loadSettings() {\\n    if (!Settings) {\\n        const settings_module = await import(\\"./api_docs/Settings.svelte\\");\\n        Settings = settings_module.default;\\n    }\\n}\\nasync function loadVibeEditor() {\\n    if (!VibeEditor) {\\n        const vibe_editor_module = await import(\\"@gradio/vibeeditor\\");\\n        VibeEditor = vibe_editor_module.default;\\n    }\\n}\\nasync function set_api_docs_visible(visible) {\\n    api_recorder_visible = false;\\n    if (visible) {\\n        await loadApiDocs();\\n    }\\n    api_docs_visible = visible;\\n    let params = new URLSearchParams(window.location.search);\\n    if (visible) {\\n        params.set(\\"view\\", \\"api\\");\\n    }\\n    else {\\n        params.delete(\\"view\\");\\n    }\\n    history.replaceState(null, \\"\\", \\"?\\" + params.toString());\\n}\\nasync function set_settings_visible(visible) {\\n    if (visible) {\\n        await loadSettings();\\n    }\\n    let params = new URLSearchParams(window.location.search);\\n    if (visible) {\\n        params.set(\\"view\\", \\"settings\\");\\n    }\\n    else {\\n        params.delete(\\"view\\");\\n    }\\n    history.replaceState(null, \\"\\", \\"?\\" + params.toString());\\n    settings_visible = !settings_visible;\\n}\\nlet api_calls = [];\\nlet layout_creating = false;\\nexport let render_complete = false;\\nasync function handle_update(data, fn_index) {\\n    const dep = dependencies.find((dep2) => dep2.id === fn_index);\\n    const input_type = components.find((comp) => comp.id === dep?.inputs[0])?.type;\\n    if (allow_zoom && dep && input_type !== \\"dataset\\") {\\n        if (dep && dep.inputs && dep.inputs.length > 0 && $is_screen_recording) {\\n            screen_recorder.zoom(true, dep.inputs, 1);\\n        }\\n        if (dep && dep.outputs && dep.outputs.length > 0 && $is_screen_recording) {\\n            screen_recorder.zoom(false, dep.outputs, 2);\\n        }\\n    }\\n    if (!dep) {\\n        return;\\n    }\\n    const outputs = dep.outputs;\\n    const meta_updates = data?.map((value, i) => {\\n        return {\\n            id: outputs[i],\\n            prop: \\"value_is_output\\",\\n            value: true\\n        };\\n    });\\n    update_value(meta_updates);\\n    await tick();\\n    const updates = [];\\n    data?.forEach((value, i) => {\\n        if (typeof value === \\"object\\" && value !== null && value.__type__ === \\"update\\") {\\n            for (const [update_key, update_value2] of Object.entries(value)) {\\n                if (update_key === \\"__type__\\") {\\n                    continue;\\n                }\\n                else {\\n                    updates.push({\\n                        id: outputs[i],\\n                        prop: update_key,\\n                        value: update_value2\\n                    });\\n                }\\n            }\\n        }\\n        else {\\n            updates.push({\\n                id: outputs[i],\\n                prop: \\"value\\",\\n                value\\n            });\\n        }\\n    });\\n    update_value(updates);\\n    await tick();\\n}\\nlet submit_map = /* @__PURE__ */ new Map();\\nlet messages = [];\\nfunction new_message(title2, message, fn_index, type, duration = 10, visible = true) {\\n    return {\\n        title: title2,\\n        message,\\n        fn_index,\\n        type,\\n        id: ++_error_id,\\n        duration,\\n        visible\\n    };\\n}\\nexport function add_new_message(title2, message, type) {\\n    messages = [new_message(title2, message, -1, type), ...messages];\\n}\\nlet _error_id = -1;\\nconst MESSAGE_QUOTE_RE = /^\'([^]+)\'$/;\\nconst DUPLICATE_MESSAGE = $_(\\"blocks.long_requests_queue\\");\\nconst MOBILE_QUEUE_WARNING = $_(\\"blocks.connection_can_break\\");\\nconst LOST_CONNECTION_MESSAGE = \\"Connection to the server was lost. Attempting reconnection...\\";\\nconst CHANGED_CONNECTION_MESSAGE = \\"Reconnected to server, but the server has changed. You may need to <a href=\'\'>refresh the page</a>.\\";\\nconst RECONNECTION_MESSAGE = \\"Connection re-established.\\";\\nconst SESSION_NOT_FOUND_MESSAGE = \\"Session not found - this is likely because the machine you were connected to has changed. <a href=\'\'>Refresh the page</a> to continue.\\";\\nconst WAITING_FOR_INPUTS_MESSAGE = $_(\\"blocks.waiting_for_inputs\\");\\nconst SHOW_DUPLICATE_MESSAGE_ON_ETA = 15;\\nconst SHOW_MOBILE_QUEUE_WARNING_ON_ETA = 10;\\nlet is_mobile_device = false;\\nlet showed_duplicate_message = false;\\nlet showed_mobile_warning = false;\\nlet inputs_waiting = [];\\nfunction wait_then_trigger_api_call(dep_index, trigger_id = null, event_data = null) {\\n    let _unsub = () => {\\n    };\\n    function unsub() {\\n        _unsub();\\n    }\\n    if ($scheduled_updates) {\\n        _unsub = scheduled_updates.subscribe((updating) => {\\n            if (!updating) {\\n                tick().then(() => {\\n                    trigger_api_call(dep_index, trigger_id, event_data);\\n                    unsub();\\n                });\\n            }\\n        });\\n    }\\n    else {\\n        trigger_api_call(dep_index, trigger_id, event_data);\\n    }\\n}\\nasync function get_component_value_or_event_data(component_id, trigger_id, event_data) {\\n    if (component_id === trigger_id && event_data && event_data.is_value_data === true) {\\n        return event_data.value;\\n    }\\n    return get_data(component_id);\\n}\\nasync function trigger_api_call(dep_index, trigger_id = null, event_data = null) {\\n    const _dep = dependencies.find((dep2) => dep2.id === dep_index);\\n    if (_dep === void 0) {\\n        return;\\n    }\\n    const dep = _dep;\\n    if (inputs_waiting.length > 0) {\\n        for (const input of inputs_waiting) {\\n            if (dep.inputs.includes(input)) {\\n                add_new_message(\\"Warning\\", WAITING_FOR_INPUTS_MESSAGE, \\"warning\\");\\n                return;\\n            }\\n        }\\n    }\\n    const current_status = loading_status.get_status_for_fn(dep_index);\\n    messages = messages.filter(({ fn_index }) => fn_index !== dep_index);\\n    if (current_status === \\"pending\\" || current_status === \\"generating\\") {\\n        dep.pending_request = true;\\n    }\\n    let payload = {\\n        fn_index: dep_index,\\n        data: await Promise.all(dep.inputs.map((id) => get_component_value_or_event_data(id, trigger_id, event_data))),\\n        event_data: dep.collects_event_data ? event_data : null,\\n        trigger_id\\n    };\\n    if (dep.frontend_fn && typeof dep.frontend_fn !== \\"boolean\\") {\\n        dep.frontend_fn(payload.data.concat(await Promise.all(dep.outputs.map((id) => get_data(id))))).then((v) => {\\n            if (dep.backend_fn) {\\n                payload.data = v;\\n                trigger_prediction(dep, payload);\\n            }\\n            else {\\n                handle_update(v, dep_index);\\n            }\\n        });\\n    }\\n    else if (dep.types.cancel && dep.cancels) {\\n        await Promise.all(dep.cancels.map(async (fn_index) => {\\n            const submission = submit_map.get(fn_index);\\n            submission?.cancel();\\n            return submission;\\n        }));\\n    }\\n    else {\\n        if (dep.backend_fn) {\\n            if (dep.js_implementation) {\\n                let js_fn = new AsyncFunction(`let result = await (${dep.js_implementation})(...arguments);\\n\\t\\t\\t\\t\\t\\treturn (!Array.isArray(result)) ? [result] : result;`);\\n                js_fn(...payload.data).then((js_result) => {\\n                    handle_update(js_result, dep_index);\\n                    payload.js_implementation = true;\\n                }).catch((error) => {\\n                    console.error(error);\\n                    payload.js_implementation = false;\\n                });\\n            }\\n            trigger_prediction(dep, payload);\\n        }\\n    }\\n    function trigger_prediction(dep2, payload2) {\\n        if (dep2.trigger_mode === \\"once\\") {\\n            if (!dep2.pending_request)\\n                make_prediction(payload2, dep2.connection == \\"stream\\");\\n        }\\n        else if (dep2.trigger_mode === \\"multiple\\") {\\n            make_prediction(payload2, dep2.connection == \\"stream\\");\\n        }\\n        else if (dep2.trigger_mode === \\"always_last\\") {\\n            if (!dep2.pending_request) {\\n                make_prediction(payload2, dep2.connection == \\"stream\\");\\n            }\\n            else {\\n                dep2.final_event = payload2;\\n            }\\n        }\\n    }\\n    async function reconnect() {\\n        const connection_status = await app.reconnect();\\n        if (connection_status === \\"broken\\") {\\n            setTimeout(reconnect, 1e3);\\n        }\\n        else if (connection_status === \\"changed\\") {\\n            broken_connection = false;\\n            messages = [\\n                new_message(\\"Changed Connection\\", CHANGED_CONNECTION_MESSAGE, -1, \\"info\\", 3, true),\\n                ...messages.map((m) => m.message === LOST_CONNECTION_MESSAGE ? { ...m, visible: false } : m)\\n            ];\\n        }\\n        else if (connection_status === \\"connected\\") {\\n            broken_connection = false;\\n            messages = [\\n                new_message(\\"Reconnected\\", RECONNECTION_MESSAGE, -1, \\"success\\", null, true),\\n                ...messages.map((m) => m.message === LOST_CONNECTION_MESSAGE ? { ...m, visible: false } : m)\\n            ];\\n        }\\n    }\\n    async function make_prediction(payload2, streaming = false) {\\n        if (allow_video_trim) {\\n            screen_recorder.markRemoveSegmentStart();\\n        }\\n        if (api_recorder_visible) {\\n            api_calls = [...api_calls, JSON.parse(JSON.stringify(payload2))];\\n        }\\n        let submission;\\n        app.set_current_payload(payload2);\\n        if (streaming) {\\n            if (!submit_map.has(dep_index)) {\\n                dep.inputs.forEach((id) => modify_stream(id, \\"waiting\\"));\\n            }\\n            else if (submit_map.has(dep_index) && dep.inputs.some((id) => get_stream_state(id) === \\"waiting\\")) {\\n                return;\\n            }\\n            else if (submit_map.has(dep_index) && dep.inputs.some((id) => get_stream_state(id) === \\"open\\")) {\\n                await app.send_ws_message(\\n                // @ts-ignore\\n                `${app.config.root + app.config.api_prefix}/stream/${submit_map.get(dep_index).event_id()}`, { ...payload2, session_hash: app.session_hash });\\n                return;\\n            }\\n        }\\n        try {\\n            submission = app.submit(payload2.fn_index, payload2.data, payload2.event_data, payload2.trigger_id);\\n        }\\n        catch (e) {\\n            const fn_index = 0;\\n            if (app.closed)\\n                return;\\n            messages = [\\n                new_message(\\"Error\\", String(e), fn_index, \\"error\\"),\\n                ...messages\\n            ];\\n            loading_status.update({\\n                status: \\"error\\",\\n                fn_index,\\n                eta: 0,\\n                queue: false,\\n                queue_position: null\\n            });\\n            set_status($loading_status);\\n            return;\\n        }\\n        submit_map.set(dep_index, submission);\\n        for await (const message of submission) {\\n            if (payload2.js_implementation) {\\n                return;\\n            }\\n            if (message.type === \\"data\\") {\\n                handle_data(message);\\n            }\\n            else if (message.type === \\"render\\") {\\n                handle_render(message);\\n            }\\n            else if (message.type === \\"status\\") {\\n                handle_status_update(message);\\n            }\\n            else if (message.type === \\"log\\") {\\n                handle_log(message);\\n            }\\n        }\\n        function handle_data(message) {\\n            const { data, fn_index } = message;\\n            if (dep.pending_request && dep.final_event) {\\n                dep.pending_request = false;\\n                make_prediction(dep.final_event, dep.connection == \\"stream\\");\\n            }\\n            dep.pending_request = false;\\n            handle_update(data, fn_index);\\n            set_status($loading_status);\\n        }\\n        function handle_render(message) {\\n            const { data } = message;\\n            let _components = data.components;\\n            let render_layout = data.layout;\\n            let _dependencies = data.dependencies;\\n            let render_id = data.render_id;\\n            let deps_to_remove = [];\\n            dependencies.forEach((old_dep, i) => {\\n                if (old_dep.rendered_in === dep.render_id) {\\n                    deps_to_remove.push(i);\\n                }\\n            });\\n            deps_to_remove.reverse().forEach((i) => {\\n                dependencies.splice(i, 1);\\n            });\\n            _dependencies.forEach((dep2) => {\\n                dependencies.push(dep2);\\n            });\\n            rerender_layout({\\n                components: _components,\\n                layout: render_layout,\\n                root: root + api_prefix,\\n                dependencies,\\n                render_id\\n            });\\n            _dependencies.forEach((dep2) => {\\n                if (dep2.targets.some((dep3) => dep3[1] === \\"load\\")) {\\n                    wait_then_trigger_api_call(dep2.id);\\n                }\\n            });\\n        }\\n        function handle_log(msg) {\\n            const { title: title2, log, fn_index, level, duration, visible } = msg;\\n            messages = [\\n                new_message(title2, log, fn_index, level, duration, visible),\\n                ...messages\\n            ];\\n        }\\n        function open_stream_events(status, id, dep2) {\\n            if (status.original_msg === \\"process_starts\\" && dep2.connection === \\"stream\\") {\\n                modify_stream(id, \\"open\\");\\n            }\\n        }\\n        function handle_status_update(message) {\\n            if (message.broken && !broken_connection) {\\n                messages = [\\n                    new_message(\\"Broken Connection\\", LOST_CONNECTION_MESSAGE, -1, \\"error\\", null, true),\\n                    ...messages\\n                ];\\n                broken_connection = true;\\n                setTimeout(reconnect, 1e3);\\n            }\\n            if (message.session_not_found) {\\n                messages = [\\n                    new_message(\\"Session Not Found\\", SESSION_NOT_FOUND_MESSAGE, -1, \\"error\\", null, true),\\n                    ...messages\\n                ];\\n            }\\n            const { fn_index, ...status } = message;\\n            if (status.stage === \\"streaming\\" && status.time_limit) {\\n                dep.inputs.forEach((id) => {\\n                    set_time_limit(id, status.time_limit);\\n                });\\n            }\\n            dep.inputs.forEach((id) => {\\n                open_stream_events(message, id, dep);\\n            });\\n            loading_status.update({\\n                ...status,\\n                time_limit: status.time_limit,\\n                status: status.stage,\\n                progress: status.progress_data,\\n                fn_index\\n            });\\n            set_status($loading_status);\\n            if (!showed_duplicate_message && space_id !== null && status.position !== void 0 && status.position >= 2 && status.eta !== void 0 && status.eta > SHOW_DUPLICATE_MESSAGE_ON_ETA) {\\n                showed_duplicate_message = true;\\n                messages = [\\n                    new_message(\\"Warning\\", DUPLICATE_MESSAGE, fn_index, \\"warning\\"),\\n                    ...messages\\n                ];\\n            }\\n            if (!showed_mobile_warning && is_mobile_device && status.eta !== void 0 && status.eta > SHOW_MOBILE_QUEUE_WARNING_ON_ETA) {\\n                showed_mobile_warning = true;\\n                messages = [\\n                    new_message(\\"Warning\\", MOBILE_QUEUE_WARNING, fn_index, \\"warning\\"),\\n                    ...messages\\n                ];\\n            }\\n            if (status.stage === \\"complete\\" || status.stage === \\"generating\\") {\\n                const deps_triggered_by_state = /* @__PURE__ */ new Set();\\n                status.changed_state_ids?.forEach((id) => {\\n                    dependencies.filter((dep2) => dep2.targets.some(([_id, _2]) => _id === id)).forEach((dep2) => {\\n                        deps_triggered_by_state.add(dep2);\\n                    });\\n                });\\n                deps_triggered_by_state.forEach((dep2) => {\\n                    wait_then_trigger_api_call(dep2.id, payload2.trigger_id);\\n                });\\n            }\\n            if (status.stage === \\"complete\\") {\\n                dependencies.forEach(async (dep2) => {\\n                    if (dep2.trigger_after === fn_index && !dep2.trigger_only_on_failure) {\\n                        wait_then_trigger_api_call(dep2.id, payload2.trigger_id);\\n                    }\\n                });\\n                dep.inputs.forEach((id) => {\\n                    modify_stream(id, \\"closed\\");\\n                });\\n                submit_map.delete(dep_index);\\n            }\\n            if (status.stage === \\"error\\" && !broken_connection && !message.session_not_found) {\\n                if (status.message) {\\n                    const _message = status.message.replace(MESSAGE_QUOTE_RE, (_2, b) => b);\\n                    const _title = status.title ?? \\"Error\\";\\n                    messages = [\\n                        new_message(_title, _message, fn_index, \\"error\\", status.duration, status.visible),\\n                        ...messages\\n                    ];\\n                }\\n                dependencies.map(async (dep2) => {\\n                    if (dep2.trigger_after === fn_index && (!dep2.trigger_only_on_success || dep2.trigger_only_on_failure)) {\\n                        wait_then_trigger_api_call(dep2.id, payload2.trigger_id);\\n                    }\\n                });\\n            }\\n        }\\n        if (allow_video_trim) {\\n            screen_recorder.markRemoveSegmentEnd();\\n        }\\n    }\\n}\\nfunction trigger_share(title2, description) {\\n    if (space_id === null) {\\n        return;\\n    }\\n    const discussion_url = new URL(`https://huggingface.co/spaces/${space_id}/discussions/new`);\\n    if (title2 !== void 0 && title2.length > 0) {\\n        discussion_url.searchParams.set(\\"title\\", title2);\\n    }\\n    discussion_url.searchParams.set(\\"description\\", description);\\n    window.open(discussion_url.toString(), \\"_blank\\");\\n}\\nfunction handle_error_close(e) {\\n    const _id = e.detail;\\n    messages = messages.filter((m) => m.id !== _id);\\n}\\nconst is_external_url = (link) => !!(link && new URL(link, location.href).origin !== location.origin);\\nasync function handle_mount() {\\n    if (js) {\\n        let blocks_frontend_fn = new AsyncFunction(`let result = await (${js})();\\n\\t\\t\\t\\t\\treturn (!Array.isArray(result)) ? [result] : result;`);\\n        await blocks_frontend_fn();\\n    }\\n    await tick();\\n    var a = target.getElementsByTagName(\\"a\\");\\n    for (var i = 0; i < a.length; i++) {\\n        const _target = a[i].getAttribute(\\"target\\");\\n        const _link = a[i].getAttribute(\\"href\\");\\n        if (is_external_url(_link) && _target !== \\"_blank\\")\\n            a[i].setAttribute(\\"target\\", \\"_blank\\");\\n    }\\n    handle_load_triggers();\\n    if (!target || render_complete)\\n        return;\\n    target.addEventListener(\\"prop_change\\", (e) => {\\n        if (!isCustomEvent(e))\\n            throw new Error(\\"not a custom event\\");\\n        const { id, prop, value } = e.detail;\\n        update_value([{ id, prop, value }]);\\n        if (prop === \\"input_ready\\" && value === false) {\\n            inputs_waiting.push(id);\\n        }\\n        if (prop === \\"input_ready\\" && value === true) {\\n            inputs_waiting = inputs_waiting.filter((item) => item !== id);\\n        }\\n    });\\n    target.addEventListener(\\"gradio\\", (e) => {\\n        if (!isCustomEvent(e))\\n            throw new Error(\\"not a custom event\\");\\n        const { id, event, data } = e.detail;\\n        if (event === \\"share\\") {\\n            const { title: title2, description } = data;\\n            trigger_share(title2, description);\\n        }\\n        else if (event === \\"error\\") {\\n            messages = [new_message(\\"Error\\", data, -1, event), ...messages];\\n        }\\n        else if (event === \\"warning\\") {\\n            messages = [new_message(\\"Warning\\", data, -1, event), ...messages];\\n        }\\n        else if (event === \\"info\\") {\\n            messages = [new_message(\\"Info\\", data, -1, event), ...messages];\\n        }\\n        else if (event == \\"clear_status\\") {\\n            update_status(id, \\"complete\\", data);\\n        }\\n        else if (event == \\"close_stream\\") {\\n            const deps = $targets[id]?.[data];\\n            deps?.forEach((dep_id) => {\\n                if (submit_map.has(dep_id)) {\\n                    const url = `${app.config.root + app.config.api_prefix}/stream/${submit_map.get(dep_id).event_id()}`;\\n                    app.post_data(`${url}/close`, {});\\n                    app.close_ws(url);\\n                }\\n            });\\n        }\\n        else {\\n            const deps = $targets[id]?.[event];\\n            deps?.forEach((dep_id) => {\\n                requestAnimationFrame(() => {\\n                    wait_then_trigger_api_call(dep_id, id, data);\\n                });\\n            });\\n        }\\n    });\\n    render_complete = true;\\n}\\nvalue_change((id, value) => {\\n    const deps = $targets[id]?.[\\"change\\"];\\n    deps?.forEach((dep_id) => {\\n        requestAnimationFrame(() => {\\n            wait_then_trigger_api_call(dep_id, id, value);\\n        });\\n    });\\n});\\nconst handle_load_triggers = () => {\\n    dependencies.forEach((dep) => {\\n        if (dep.targets.some((dep2) => dep2[1] === \\"load\\")) {\\n            wait_then_trigger_api_call(dep.id);\\n        }\\n    });\\n};\\n$: set_status($loading_status);\\nfunction update_status(id, status, data) {\\n    data.status = status;\\n    update_value([\\n        {\\n            id,\\n            prop: \\"loading_status\\",\\n            value: data\\n        }\\n    ]);\\n}\\nfunction set_status(statuses) {\\n    let updates = [];\\n    Object.entries(statuses).forEach(([id, loading_status2]) => {\\n        if (app.closed && loading_status2.status === \\"error\\") {\\n            return;\\n        }\\n        let dependency = dependencies.find((dep) => dep.id == loading_status2.fn_index);\\n        if (dependency === void 0) {\\n            return;\\n        }\\n        loading_status2.scroll_to_output = dependency.scroll_to_output;\\n        loading_status2.show_progress = dependency.show_progress;\\n        updates.push({\\n            id: parseInt(id),\\n            prop: \\"loading_status\\",\\n            value: loading_status2\\n        });\\n    });\\n    const inputs_to_update = loading_status.get_inputs_to_update();\\n    const additional_updates = Array.from(inputs_to_update).map(([id, pending_status]) => {\\n        return {\\n            id,\\n            prop: \\"pending\\",\\n            value: pending_status === \\"pending\\"\\n        };\\n    });\\n    update_value([...updates, ...additional_updates]);\\n}\\nfunction isCustomEvent(event) {\\n    return \\"detail\\" in event;\\n}\\nlet is_screen_recording = writable(false);\\nonMount(() => {\\n    is_mobile_device = /Android|webOS|iPhone|iPad|iPod|BlackBerry|IEMobile|Opera Mini/i.test(navigator.userAgent);\\n    screen_recorder.initialize(root, (title2, message, type) => {\\n        add_new_message(title2, message, type);\\n    }, (isRecording) => {\\n        $is_screen_recording = isRecording;\\n    });\\n    const handleVibeEditorResize = (event) => {\\n        vibe_editor_width = event.detail.width;\\n    };\\n    window.addEventListener(\\"vibeEditorResize\\", handleVibeEditorResize);\\n    if (api_docs_visible) {\\n        loadApiDocs();\\n    }\\n    if (api_recorder_visible) {\\n        loadApiRecorder();\\n    }\\n    if (settings_visible) {\\n        loadSettings();\\n    }\\n    if (vibe_mode) {\\n        loadVibeEditor();\\n    }\\n});\\nfunction screen_recording() {\\n    if ($is_screen_recording) {\\n        screen_recorder.stopRecording();\\n    }\\n    else {\\n        screen_recorder.startRecording();\\n    }\\n}\\n<\/script>\\n\\n<svelte:head>\\n\\t{#if control_page_title}\\n\\t\\t<title>{title}</title>\\n\\t{/if}\\n\\t{#if css}\\n\\t\\t{@html `\\\\<style\\\\>${prefix_css(css, version)}</style>`}\\n\\t{/if}\\n</svelte:head>\\n\\n<div class=\\"wrap\\" style:min-height={app_mode ? \\"100%\\" : \\"auto\\"}>\\n\\t<div\\n\\t\\tclass=\\"contain\\"\\n\\t\\tstyle:flex-grow={app_mode ? \\"1\\" : \\"auto\\"}\\n\\t\\tstyle:margin-right={vibe_mode ? `${vibe_editor_width}px` : \\"0\\"}\\n\\t>\\n\\t\\t{#if $_layout && app.config}\\n\\t\\t\\t<MountComponents\\n\\t\\t\\t\\trootNode={$_layout}\\n\\t\\t\\t\\t{root}\\n\\t\\t\\t\\t{target}\\n\\t\\t\\t\\t{theme_mode}\\n\\t\\t\\t\\ton:mount={handle_mount}\\n\\t\\t\\t\\t{version}\\n\\t\\t\\t\\t{autoscroll}\\n\\t\\t\\t\\t{max_file_size}\\n\\t\\t\\t\\tclient={app}\\n\\t\\t\\t/>\\n\\t\\t{/if}\\n\\t</div>\\n\\n\\t{#if show_footer}\\n\\t\\t<footer>\\n\\t\\t\\t{#if show_api}\\n\\t\\t\\t\\t<button\\n\\t\\t\\t\\t\\ton:click={() => {\\n\\t\\t\\t\\t\\t\\tset_api_docs_visible(!api_docs_visible);\\n\\t\\t\\t\\t\\t}}\\n\\t\\t\\t\\t\\ton:mouseenter={() => {\\n\\t\\t\\t\\t\\t\\tloadApiDocs();\\n\\t\\t\\t\\t\\t\\tloadApiRecorder();\\n\\t\\t\\t\\t\\t}}\\n\\t\\t\\t\\t\\tclass=\\"show-api\\"\\n\\t\\t\\t\\t>\\n\\t\\t\\t\\t\\t{#if app.config?.mcp_server}\\n\\t\\t\\t\\t\\t\\t{$_(\\"errors.use_via_api_or_mcp\\")}\\n\\t\\t\\t\\t\\t{:else}\\n\\t\\t\\t\\t\\t\\t{$_(\\"errors.use_via_api\\")}\\n\\t\\t\\t\\t\\t{/if}\\n\\t\\t\\t\\t\\t<img src={api_logo} alt={$_(\\"common.logo\\")} />\\n\\t\\t\\t\\t</button>\\n\\t\\t\\t\\t<div class=\\"divider show-api-divider\\">·</div>\\n\\t\\t\\t{/if}\\n\\t\\t\\t<a\\n\\t\\t\\t\\thref=\\"https://gradio.app\\"\\n\\t\\t\\t\\tclass=\\"built-with\\"\\n\\t\\t\\t\\ttarget=\\"_blank\\"\\n\\t\\t\\t\\trel=\\"noreferrer\\"\\n\\t\\t\\t>\\n\\t\\t\\t\\t{$_(\\"common.built_with_gradio\\")}\\n\\t\\t\\t\\t<img src={logo} alt={$_(\\"common.logo\\")} />\\n\\t\\t\\t</a>\\n\\t\\t\\t<div class=\\"divider\\" class:hidden={!$is_screen_recording}>·</div>\\n\\t\\t\\t<button\\n\\t\\t\\t\\tclass:hidden={!$is_screen_recording}\\n\\t\\t\\t\\ton:click={() => {\\n\\t\\t\\t\\t\\tscreen_recording();\\n\\t\\t\\t\\t}}\\n\\t\\t\\t\\tclass=\\"record\\"\\n\\t\\t\\t>\\n\\t\\t\\t\\t{$_(\\"common.stop_recording\\")}\\n\\t\\t\\t\\t<img src={record_stop} alt={$_(\\"common.stop_recording\\")} />\\n\\t\\t\\t</button>\\n\\t\\t\\t<div class=\\"divider\\">·</div>\\n\\t\\t\\t<button\\n\\t\\t\\t\\ton:click={() => {\\n\\t\\t\\t\\t\\tset_settings_visible(!settings_visible);\\n\\t\\t\\t\\t}}\\n\\t\\t\\t\\ton:mouseenter={() => {\\n\\t\\t\\t\\t\\tloadSettings();\\n\\t\\t\\t\\t}}\\n\\t\\t\\t\\tclass=\\"settings\\"\\n\\t\\t\\t>\\n\\t\\t\\t\\t{$_(\\"common.settings\\")}\\n\\t\\t\\t\\t<img src={settings_logo} alt={$_(\\"common.settings\\")} />\\n\\t\\t\\t</button>\\n\\t\\t</footer>\\n\\t{/if}\\n</div>\\n\\n{#if api_recorder_visible && ApiRecorder}\\n\\t<!-- TODO: fix -->\\n\\t<!-- svelte-ignore a11y-click-events-have-key-events-->\\n\\t<!-- svelte-ignore a11y-no-static-element-interactions-->\\n\\t<div\\n\\t\\tid=\\"api-recorder-container\\"\\n\\t\\ton:click={() => {\\n\\t\\t\\tset_api_docs_visible(true);\\n\\t\\t\\tapi_recorder_visible = false;\\n\\t\\t}}\\n\\t>\\n\\t\\t<svelte:component this={ApiRecorder} {api_calls} {dependencies} />\\n\\t</div>\\n{/if}\\n\\n{#if api_docs_visible && $_layout && ApiDocs}\\n\\t<div class=\\"api-docs\\">\\n\\t\\t<!-- TODO: fix -->\\n\\t\\t<!-- svelte-ignore a11y-click-events-have-key-events-->\\n\\t\\t<!-- svelte-ignore a11y-no-static-element-interactions-->\\n\\t\\t<div\\n\\t\\t\\tclass=\\"backdrop\\"\\n\\t\\t\\ton:click={() => {\\n\\t\\t\\t\\tset_api_docs_visible(false);\\n\\t\\t\\t}}\\n\\t\\t/>\\n\\t\\t<div class=\\"api-docs-wrap\\">\\n\\t\\t\\t<svelte:component\\n\\t\\t\\t\\tthis={ApiDocs}\\n\\t\\t\\t\\troot_node={$_layout}\\n\\t\\t\\t\\ton:close={(event) => {\\n\\t\\t\\t\\t\\tset_api_docs_visible(false);\\n\\t\\t\\t\\t\\tapi_calls = [];\\n\\t\\t\\t\\t\\tapi_recorder_visible = api_recorder_visible =\\n\\t\\t\\t\\t\\t\\tevent.detail?.api_recorder_visible;\\n\\t\\t\\t\\t}}\\n\\t\\t\\t\\t{dependencies}\\n\\t\\t\\t\\t{root}\\n\\t\\t\\t\\t{app}\\n\\t\\t\\t\\t{space_id}\\n\\t\\t\\t\\t{api_calls}\\n\\t\\t\\t\\t{username}\\n\\t\\t\\t/>\\n\\t\\t</div>\\n\\t</div>\\n{/if}\\n\\n{#if settings_visible && $_layout && app.config && Settings}\\n\\t<div class=\\"api-docs\\">\\n\\t\\t<!-- TODO: fix -->\\n\\t\\t<!-- svelte-ignore a11y-click-events-have-key-events-->\\n\\t\\t<!-- svelte-ignore a11y-no-static-element-interactions-->\\n\\t\\t<div\\n\\t\\t\\tclass=\\"backdrop\\"\\n\\t\\t\\ton:click={() => {\\n\\t\\t\\t\\tset_settings_visible(false);\\n\\t\\t\\t}}\\n\\t\\t/>\\n\\t\\t<div class=\\"api-docs-wrap\\">\\n\\t\\t\\t<svelte:component\\n\\t\\t\\t\\tthis={Settings}\\n\\t\\t\\t\\tbind:allow_zoom\\n\\t\\t\\t\\tbind:allow_video_trim\\n\\t\\t\\t\\ton:close={() => {\\n\\t\\t\\t\\t\\tset_settings_visible(false);\\n\\t\\t\\t\\t}}\\n\\t\\t\\t\\ton:start_recording={() => {\\n\\t\\t\\t\\t\\tscreen_recording();\\n\\t\\t\\t\\t}}\\n\\t\\t\\t\\tpwa_enabled={app.config.pwa}\\n\\t\\t\\t\\t{root}\\n\\t\\t\\t\\t{space_id}\\n\\t\\t\\t/>\\n\\t\\t</div>\\n\\t</div>\\n{/if}\\n\\n{#if messages}\\n\\t<Toast {messages} on:close={handle_error_close} />\\n{/if}\\n\\n{#if vibe_mode && VibeEditor}\\n\\t<svelte:component this={VibeEditor} {app} {root} />\\n{/if}\\n\\n<style>\\n\\t.wrap {\\n\\t\\tdisplay: flex;\\n\\t\\tflex-grow: 1;\\n\\t\\tflex-direction: column;\\n\\t\\twidth: var(--size-full);\\n\\t\\tfont-weight: var(--body-text-weight);\\n\\t\\tfont-size: var(--body-text-size);\\n\\t}\\n\\n\\t.contain {\\n\\t\\tdisplay: flex;\\n\\t\\tflex-direction: column;\\n\\t}\\n\\n\\tfooter {\\n\\t\\tdisplay: flex;\\n\\t\\tjustify-content: center;\\n\\t\\tmargin-top: var(--size-4);\\n\\t\\tcolor: var(--body-text-color-subdued);\\n\\t}\\n\\t.divider {\\n\\t\\tmargin-left: var(--size-1);\\n\\t\\tmargin-right: var(--size-2);\\n\\t}\\n\\n\\t.show-api,\\n\\t.settings,\\n\\t.record {\\n\\t\\tdisplay: flex;\\n\\t\\talign-items: center;\\n\\t}\\n\\t.show-api:hover {\\n\\t\\tcolor: var(--body-text-color);\\n\\t}\\n\\n\\t.show-api img {\\n\\t\\tmargin-right: var(--size-1);\\n\\t\\tmargin-left: var(--size-2);\\n\\t\\twidth: var(--size-3);\\n\\t}\\n\\n\\t.settings img {\\n\\t\\tmargin-right: var(--size-1);\\n\\t\\tmargin-left: var(--size-1);\\n\\t\\twidth: var(--size-4);\\n\\t}\\n\\n\\t.record img {\\n\\t\\tmargin-right: var(--size-1);\\n\\t\\tmargin-left: var(--size-1);\\n\\t\\twidth: var(--size-3);\\n\\t}\\n\\n\\t.built-with {\\n\\t\\tdisplay: flex;\\n\\t\\talign-items: center;\\n\\t}\\n\\n\\t.built-with:hover,\\n\\t.settings:hover,\\n\\t.record:hover {\\n\\t\\tcolor: var(--body-text-color);\\n\\t}\\n\\n\\t.built-with img {\\n\\t\\tmargin-right: var(--size-1);\\n\\t\\tmargin-left: var(--size-1);\\n\\t\\tmargin-bottom: 1px;\\n\\t\\twidth: var(--size-4);\\n\\t}\\n\\n\\t.api-docs {\\n\\t\\tdisplay: flex;\\n\\t\\tposition: fixed;\\n\\t\\ttop: 0;\\n\\t\\tright: 0;\\n\\t\\tz-index: var(--layer-top);\\n\\t\\tbackground: rgba(0, 0, 0, 0.5);\\n\\t\\twidth: var(--size-screen);\\n\\t\\theight: var(--size-screen-h);\\n\\t}\\n\\n\\t.backdrop {\\n\\t\\tflex: 1 1 0%;\\n\\t\\t-webkit-backdrop-filter: blur(4px);\\n\\t\\tbackdrop-filter: blur(4px);\\n\\t}\\n\\n\\t.api-docs-wrap {\\n\\t\\tbox-shadow: var(--shadow-drop-lg);\\n\\t\\tbackground: var(--background-fill-primary);\\n\\t\\toverflow-x: hidden;\\n\\t\\toverflow-y: auto;\\n\\t}\\n\\n\\t@media (min-width: 768px) {\\n\\t\\t.api-docs-wrap {\\n\\t\\t\\tborder-top-left-radius: var(--radius-lg);\\n\\t\\t\\tborder-bottom-left-radius: var(--radius-lg);\\n\\t\\t\\twidth: 950px;\\n\\t\\t}\\n\\t}\\n\\n\\t@media (min-width: 1536px) {\\n\\t\\t.api-docs-wrap {\\n\\t\\t\\twidth: 1150px;\\n\\t\\t}\\n\\t}\\n\\n\\t#api-recorder-container {\\n\\t\\tposition: fixed;\\n\\t\\tleft: 10px;\\n\\t\\tbottom: 10px;\\n\\t\\tz-index: 1000;\\n\\t}\\n\\n\\t.show-api {\\n\\t\\tdisplay: flex;\\n\\t\\talign-items: center;\\n\\t}\\n\\n\\t@media (max-width: 640px) {\\n\\t\\t.show-api,\\n\\t\\t.show-api-divider {\\n\\t\\t\\tdisplay: none;\\n\\t\\t}\\n\\t}\\n\\n\\t.show-api:hover {\\n\\t\\tcolor: var(--body-text-color);\\n\\t}\\n\\n\\t.hidden {\\n\\t\\tdisplay: none;\\n\\t}</style>\\n"],"names":[],"mappings":"AAk4BC,iCAAM,CACL,OAAO,CAAE,IAAI,CACb,SAAS,CAAE,CAAC,CACZ,cAAc,CAAE,MAAM,CACtB,KAAK,CAAE,IAAI,WAAW,CAAC,CACvB,WAAW,CAAE,IAAI,kBAAkB,CAAC,CACpC,SAAS,CAAE,IAAI,gBAAgB,CAChC,CAEA,oCAAS,CACR,OAAO,CAAE,IAAI,CACb,cAAc,CAAE,MACjB,CAEA,kCAAO,CACN,OAAO,CAAE,IAAI,CACb,eAAe,CAAE,MAAM,CACvB,UAAU,CAAE,IAAI,QAAQ,CAAC,CACzB,KAAK,CAAE,IAAI,yBAAyB,CACrC,CACA,oCAAS,CACR,WAAW,CAAE,IAAI,QAAQ,CAAC,CAC1B,YAAY,CAAE,IAAI,QAAQ,CAC3B,CAEA,qCAAS,CACT,qCAAS,CACT,mCAAQ,CACP,OAAO,CAAE,IAAI,CACb,WAAW,CAAE,MACd,CACA,qCAAS,MAAO,CACf,KAAK,CAAE,IAAI,iBAAiB,CAC7B,CAEA,uBAAS,CAAC,iBAAI,CACb,YAAY,CAAE,IAAI,QAAQ,CAAC,CAC3B,WAAW,CAAE,IAAI,QAAQ,CAAC,CAC1B,KAAK,CAAE,IAAI,QAAQ,CACpB,CAEA,uBAAS,CAAC,iBAAI,CACb,YAAY,CAAE,IAAI,QAAQ,CAAC,CAC3B,WAAW,CAAE,IAAI,QAAQ,CAAC,CAC1B,KAAK,CAAE,IAAI,QAAQ,CACpB,CAEA,qBAAO,CAAC,iBAAI,CACX,YAAY,CAAE,IAAI,QAAQ,CAAC,CAC3B,WAAW,CAAE,IAAI,QAAQ,CAAC,CAC1B,KAAK,CAAE,IAAI,QAAQ,CACpB,CAEA,uCAAY,CACX,OAAO,CAAE,IAAI,CACb,WAAW,CAAE,MACd,CAEA,uCAAW,MAAM,CACjB,qCAAS,MAAM,CACf,mCAAO,MAAO,CACb,KAAK,CAAE,IAAI,iBAAiB,CAC7B,CAEA,yBAAW,CAAC,iBAAI,CACf,YAAY,CAAE,IAAI,QAAQ,CAAC,CAC3B,WAAW,CAAE,IAAI,QAAQ,CAAC,CAC1B,aAAa,CAAE,GAAG,CAClB,KAAK,CAAE,IAAI,QAAQ,CACpB,CAEA,qCAAU,CACT,OAAO,CAAE,IAAI,CACb,QAAQ,CAAE,KAAK,CACf,GAAG,CAAE,CAAC,CACN,KAAK,CAAE,CAAC,CACR,OAAO,CAAE,IAAI,WAAW,CAAC,CACzB,UAAU,CAAE,KAAK,CAAC,CAAC,CAAC,CAAC,CAAC,CAAC,CAAC,CAAC,CAAC,GAAG,CAAC,CAC9B,KAAK,CAAE,IAAI,aAAa,CAAC,CACzB,MAAM,CAAE,IAAI,eAAe,CAC5B,CAEA,qCAAU,CACT,IAAI,CAAE,CAAC,CAAC,CAAC,CAAC,EAAE,CACZ,uBAAuB,CAAE,KAAK,GAAG,CAAC,CAClC,eAAe,CAAE,KAAK,GAAG,CAC1B,CAEA,0CAAe,CACd,UAAU,CAAE,IAAI,gBAAgB,CAAC,CACjC,UAAU,CAAE,IAAI,yBAAyB,CAAC,CAC1C,UAAU,CAAE,MAAM,CAClB,UAAU,CAAE,IACb,CAEA,MAAO,YAAY,KAAK,CAAE,CACzB,0CAAe,CACd,sBAAsB,CAAE,IAAI,WAAW,CAAC,CACxC,yBAAyB,CAAE,IAAI,WAAW,CAAC,CAC3C,KAAK,CAAE,KACR,CACD,CAEA,MAAO,YAAY,MAAM,CAAE,CAC1B,0CAAe,CACd,KAAK,CAAE,MACR,CACD,CAEA,mDAAwB,CACvB,QAAQ,CAAE,KAAK,CACf,IAAI,CAAE,IAAI,CACV,MAAM,CAAE,IAAI,CACZ,OAAO,CAAE,IACV,CAEA,qCAAU,CACT,OAAO,CAAE,IAAI,CACb,WAAW,CAAE,MACd,CAEA,MAAO,YAAY,KAAK,CAAE,CACzB,qCAAS,CACT,6CAAkB,CACjB,OAAO,CAAE,IACV,CACD,CAEA,qCAAS,MAAO,CACf,KAAK,CAAE,IAAI,iBAAiB,CAC7B,CAEA,mCAAQ,CACP,OAAO,CAAE,IACV"}'},rn=/^'([^]+)'$/,Le="Connection to the server was lost. Attempting reconnection...",ln="Reconnected to server, but the server has changed. You may need to <a href=''>refresh the page</a>.",dn="Connection re-established.",cn="Session not found - this is likely because the machine you were connected to has changed. <a href=''>Refresh the page</a> to continue.",_n=15,pn=create_ssr_component((a,e,t,H)=>{let r,b,p,n,E,v,u,y,l,I,x,O;I=subscribe(xt$2,i=>l=i);let{root:T}=e,{components:G}=e,{layout:q}=e,{dependencies:g}=e,{title:A="Gradio"}=e,{target:Q}=e,{autoscroll:se}=e,{show_api:S=!0}=e,{show_footer:L=!0}=e,{control_page_title:Z=!1}=e,{app_mode:ie}=e,{theme_mode:J}=e,{app:h}=e,{space_id:X}=e,{version:K}=e,{js:ue}=e,{fill_height:ae=!1}=e,{ready:be}=e,{username:Ee}=e,{api_prefix:me=""}=e,{max_file_size:ye=void 0}=e,{initial_layout:xe=void 0}=e,{css:fe=null}=e,{vibe_mode:re=!1}=e,le=!1,{layout:dt,targets:ct,update_value:ze,get_data:We,modify_stream:Ie,get_stream_state:Qe,set_time_limit:_t,loading_status:de,scheduled_updates:Ke,create_layout:At,rerender_layout:pt,value_change:ut}=Ys({initial_layout:xe});O=subscribe(dt,i=>x=i),v=subscribe(ct,i=>E=i),n=subscribe(de,i=>p=i),y=subscribe(Ke,i=>u=i);let je=g,De=350;async function mt(){await oa(h.config?.i18n_translations||void 0),Be=!0,await At({components:G,layout:q,dependencies:g,root:T+me,app:h,options:{fill_height:ae}}),Be=!1;}let{search_params:ce}=e,qe=ce.get("view")==="api"&&S,Pe=ce.get("view")==="settings",Se=ce.get("view")==="api-recorder"&&S,ke=!0,Fe=!0,_e=null,$=null,ve=null,ge=null;let Ce=[],Be=!1,{render_complete:Oe=!1}=e;async function Me(i,f){const _=g.find(N=>N.id===f),R=G.find(N=>N.id===_?.inputs[0])?.type;if(ke&&_&&R!=="dataset"&&(_&&_.inputs&&_.inputs.length>0&&r&&(_.inputs,void 0),_&&_.outputs&&_.outputs.length>0&&r&&(_.outputs,void 0)),!_)return;const o=_.outputs,B=i?.map((N,te)=>({id:o[te],prop:"value_is_output",value:!0}));ze(B),await tick();const M=[];i?.forEach((N,te)=>{if(typeof N=="object"&&N!==null&&N.__type__==="update")for(const[ne,s]of Object.entries(N))ne!=="__type__"&&M.push({id:o[te],prop:ne,value:s});else M.push({id:o[te],prop:"value",value:N});}),ze(M),await tick();}let ee=new Map,m=[];function U(i,f,_,R,o=10,B=!0){return {title:i,message:f,fn_index:_,type:R,id:++ht,duration:o,visible:B}}function Ne(i,f,_){m=[U(i,f,-1,_),...m];}let ht=-1;const wt=l("blocks.long_requests_queue");l("blocks.connection_can_break");const Et=l("blocks.waiting_for_inputs");let Ve=!1,Ze=[];function oe(i,f=null,_=null){let R=()=>{};function o(){R();}u?R=Ke.subscribe(B=>{B||tick().then(()=>{Je(i,f,_),o();});}):Je(i,f,_);}async function yt$1(i,f,_){return i===f&&_&&_.is_value_data===!0?_.value:We(i)}async function Je(i,f=null,_=null){const R=g.find(s=>s.id===i);if(R===void 0)return;const o=R;if(Ze.length>0){for(const s of Ze)if(o.inputs.includes(s)){Ne("Warning",Et,"warning");return}}const B=de.get_status_for_fn(i);m=m.filter(({fn_index:s})=>s!==i),(B==="pending"||B==="generating")&&(o.pending_request=!0);let M={fn_index:i,data:await Promise.all(o.inputs.map(s=>yt$1(s,f,_))),event_data:o.collects_event_data?_:null,trigger_id:f};o.frontend_fn&&typeof o.frontend_fn!="boolean"?o.frontend_fn(M.data.concat(await Promise.all(o.outputs.map(s=>We(s))))).then(s=>{o.backend_fn?(M.data=s,N(o,M)):Me(s,i);}):o.types.cancel&&o.cancels?await Promise.all(o.cancels.map(async s=>{const w=ee.get(s);return w?.cancel(),w})):o.backend_fn&&(o.js_implementation&&new Bo(`let result = await (${o.js_implementation})(...arguments);
						return (!Array.isArray(result)) ? [result] : result;`)(...M.data).then(w=>{Me(w,i),M.js_implementation=!0;}).catch(w=>{console.error(w),M.js_implementation=!1;}),N(o,M));function N(s,w){s.trigger_mode==="once"?s.pending_request||ne(w,s.connection=="stream"):s.trigger_mode==="multiple"?ne(w,s.connection=="stream"):s.trigger_mode==="always_last"&&(s.pending_request?s.final_event=w:ne(w,s.connection=="stream"));}async function te(){const s=await h.reconnect();s==="broken"?setTimeout(te,1e3):s==="changed"?(le=!1,m=[U("Changed Connection",ln,-1,"info",3,!0),...m.map(w=>w.message===Le?{...w,visible:!1}:w)]):s==="connected"&&(le=!1,m=[U("Reconnected",dn,-1,"success",null,!0),...m.map(w=>w.message===Le?{...w,visible:!1}:w)]);}async function ne(s,w=!1){Se&&(Ce=[...Ce,JSON.parse(JSON.stringify(s))]);let Te;if(h.set_current_payload(s),w)if(!ee.has(i))o.inputs.forEach(c=>Ie(c,"waiting"));else {if(ee.has(i)&&o.inputs.some(c=>Qe(c)==="waiting"))return;if(ee.has(i)&&o.inputs.some(c=>Qe(c)==="open")){await h.send_ws_message(`${h.config.root+h.config.api_prefix}/stream/${ee.get(i).event_id()}`,{...s,session_hash:h.session_hash});return}}try{Te=h.submit(s.fn_index,s.data,s.event_data,s.trigger_id);}catch(c){if(h.closed)return;m=[U("Error",String(c),0,"error"),...m],de.update({status:"error",fn_index:0,eta:0,queue:!1,queue_position:null}),he(p);return}ee.set(i,Te);for await(const c of Te){if(s.js_implementation)return;c.type==="data"?St(c):c.type==="render"?kt(c):c.type==="status"?Mt(c):c.type==="log"&&Bt(c);}function St(c){const{data:z,fn_index:d}=c;o.pending_request&&o.final_event&&(o.pending_request=!1,ne(o.final_event,o.connection=="stream")),o.pending_request=!1,Me(z,d),he(p);}function kt(c){const{data:z}=c;let d=z.components,C=z.layout,W=z.dependencies,P=z.render_id,F=[];g.forEach((j,Re)=>{j.rendered_in===o.render_id&&F.push(Re);}),F.reverse().forEach(j=>{g.splice(j,1);}),W.forEach(j=>{g.push(j);}),pt({components:d,layout:C,root:T+me,dependencies:g,render_id:P}),W.forEach(j=>{j.targets.some(Re=>Re[1]==="load")&&oe(j.id);});}function Bt(c){const{title:z,log:d,fn_index:C,level:W,duration:P,visible:F}=c;m=[U(z,d,C,W,P,F),...m];}function Ot(c,z,d){c.original_msg==="process_starts"&&d.connection==="stream"&&Ie(z,"open");}function Mt(c){c.broken&&!le&&(m=[U("Broken Connection",Le,-1,"error",null,!0),...m],le=!0,setTimeout(te,1e3)),c.session_not_found&&(m=[U("Session Not Found",cn,-1,"error",null,!0),...m]);const{fn_index:z,...d}=c;if(d.stage==="streaming"&&d.time_limit&&o.inputs.forEach(C=>{_t(C,d.time_limit);}),o.inputs.forEach(C=>{Ot(c,C,o);}),de.update({...d,time_limit:d.time_limit,status:d.stage,progress:d.progress_data,fn_index:z}),he(p),!Ve&&X!==null&&d.position!==void 0&&d.position>=2&&d.eta!==void 0&&d.eta>_n&&(Ve=!0,m=[U("Warning",wt,z,"warning"),...m]),d.stage==="complete"||d.stage==="generating"){const C=new Set;d.changed_state_ids?.forEach(W=>{g.filter(P=>P.targets.some(([F,j])=>F===W)).forEach(P=>{C.add(P);});}),C.forEach(W=>{oe(W.id,s.trigger_id);});}if(d.stage==="complete"&&(g.forEach(async C=>{C.trigger_after===z&&!C.trigger_only_on_failure&&oe(C.id,s.trigger_id);}),o.inputs.forEach(C=>{Ie(C,"closed");}),ee.delete(i)),d.stage==="error"&&!le&&!c.session_not_found){if(d.message){const C=d.message.replace(rn,(P,F)=>F),W=d.title??"Error";m=[U(W,C,z,"error",d.duration,d.visible),...m];}g.map(async C=>{C.trigger_after===z&&(!C.trigger_only_on_success||C.trigger_only_on_failure)&&oe(C.id,s.trigger_id);});}}}}ut((i,f)=>{E[i]?.change?.forEach(R=>{requestAnimationFrame(()=>{oe(R,i,f);});});});const xt=()=>{g.forEach(i=>{i.targets.some(f=>f[1]==="load")&&oe(i.id);});};function he(i){let f=[];Object.entries(i).forEach(([o,B])=>{if(h.closed&&B.status==="error")return;let M=g.find(N=>N.id==B.fn_index);M!==void 0&&(B.scroll_to_output=M.scroll_to_output,B.show_progress=M.show_progress,f.push({id:parseInt(o),prop:"loading_status",value:B}));});const _=de.get_inputs_to_update(),R=Array.from(_).map(([o,B])=>({id:o,prop:"pending",value:B==="pending"}));ze([...f,...R]);}let zt=writable(!1);b=subscribe(zt,i=>r=i),e.root===void 0&&t.root&&T!==void 0&&t.root(T),e.components===void 0&&t.components&&G!==void 0&&t.components(G),e.layout===void 0&&t.layout&&q!==void 0&&t.layout(q),e.dependencies===void 0&&t.dependencies&&g!==void 0&&t.dependencies(g),e.title===void 0&&t.title&&A!==void 0&&t.title(A),e.target===void 0&&t.target&&Q!==void 0&&t.target(Q),e.autoscroll===void 0&&t.autoscroll&&se!==void 0&&t.autoscroll(se),e.show_api===void 0&&t.show_api&&S!==void 0&&t.show_api(S),e.show_footer===void 0&&t.show_footer&&L!==void 0&&t.show_footer(L),e.control_page_title===void 0&&t.control_page_title&&Z!==void 0&&t.control_page_title(Z),e.app_mode===void 0&&t.app_mode&&ie!==void 0&&t.app_mode(ie),e.theme_mode===void 0&&t.theme_mode&&J!==void 0&&t.theme_mode(J),e.app===void 0&&t.app&&h!==void 0&&t.app(h),e.space_id===void 0&&t.space_id&&X!==void 0&&t.space_id(X),e.version===void 0&&t.version&&K!==void 0&&t.version(K),e.js===void 0&&t.js&&ue!==void 0&&t.js(ue),e.fill_height===void 0&&t.fill_height&&ae!==void 0&&t.fill_height(ae),e.ready===void 0&&t.ready&&be!==void 0&&t.ready(be),e.username===void 0&&t.username&&Ee!==void 0&&t.username(Ee),e.api_prefix===void 0&&t.api_prefix&&me!==void 0&&t.api_prefix(me),e.max_file_size===void 0&&t.max_file_size&&ye!==void 0&&t.max_file_size(ye),e.initial_layout===void 0&&t.initial_layout&&xe!==void 0&&t.initial_layout(xe),e.css===void 0&&t.css&&fe!==void 0&&t.css(fe),e.vibe_mode===void 0&&t.vibe_mode&&re!==void 0&&t.vibe_mode(re),e.search_params===void 0&&t.search_params&&ce!==void 0&&t.search_params(ce),e.render_complete===void 0&&t.render_complete&&Oe!==void 0&&t.render_complete(Oe),e.add_new_message===void 0&&t.add_new_message&&Ne!==void 0&&t.add_new_message(Ne),a.css.add(an);let we,Xe,It=a.head;do we=!0,a.head=It,mt(),be=!!x,g!==je&&Oe&&!Be&&(xt(),je=g),he(p),Xe=`${a.head+=`<!-- HEAD_svelte-eiigye_START -->${Z?`${a.title=`<title>${escape(A)}</title>`,""}`:""}${fe?`<!-- HTML_TAG_START -->${`<style>${Zs(fe,K)}</style>`}<!-- HTML_TAG_END -->`:""}<!-- HEAD_svelte-eiigye_END -->`,""} <div class="wrap svelte-czcr5b"${add_styles({"min-height":ie?"100%":"auto"})}><div class="contain svelte-czcr5b"${add_styles({"flex-grow":ie?"1":"auto","margin-right":re?`${De}px`:"0"})}>${x&&h.config?`${validate_component(en,"MountComponents").$$render(a,{rootNode:x,root:T,target:Q,theme_mode:J,version:K,autoscroll:se,max_file_size:ye,client:h},{},{})}`:""}</div> ${L?`<footer class="svelte-czcr5b">${S?`<button class="show-api svelte-czcr5b">${h.config?.mcp_server?`${escape(l("errors.use_via_api_or_mcp"))}`:`${escape(l("errors.use_via_api"))}`} <img${add_attribute("src",nn,0)}${add_attribute("alt",l("common.logo"),0)} class="svelte-czcr5b"></button> <div class="divider show-api-divider svelte-czcr5b" data-svelte-h="svelte-1b2w0qd">·</div>`:""} <a href="https://gradio.app" class="built-with svelte-czcr5b" target="_blank" rel="noreferrer">${escape(l("common.built_with_gradio"))} <img${add_attribute("src",tn,0)}${add_attribute("alt",l("common.logo"),0)} class="svelte-czcr5b"></a> <div class="${["divider svelte-czcr5b",r?"":"hidden"].join(" ").trim()}" data-svelte-h="svelte-8g02jg">·</div> <button class="${["record svelte-czcr5b",r?"":"hidden"].join(" ").trim()}">${escape(l("common.stop_recording"))} <img${add_attribute("src",sn,0)}${add_attribute("alt",l("common.stop_recording"),0)} class="svelte-czcr5b"></button> <div class="divider svelte-czcr5b" data-svelte-h="svelte-1r8d4nl">·</div> <button class="settings svelte-czcr5b">${escape(l("common.settings"))} <img${add_attribute("src",on,0)}${add_attribute("alt",l("common.settings"),0)} class="svelte-czcr5b"></button></footer>`:""}</div> ${Se&&$?`   <div id="api-recorder-container" class="svelte-czcr5b">${validate_component(missing_component,"svelte:component").$$render(a,{api_calls:Ce,dependencies:g},{},{})}</div>`:""} ${qe&&x&&_e?`<div class="api-docs svelte-czcr5b">   <div class="backdrop svelte-czcr5b"></div> <div class="api-docs-wrap svelte-czcr5b">${validate_component(missing_component,"svelte:component").$$render(a,{root_node:x,dependencies:g,root:T,app:h,space_id:X,api_calls:Ce,username:Ee},{},{})}</div></div>`:""} ${Pe&&x&&h.config&&ve?`<div class="api-docs svelte-czcr5b">   <div class="backdrop svelte-czcr5b"></div> <div class="api-docs-wrap svelte-czcr5b">${validate_component(missing_component,"svelte:component").$$render(a,{pwa_enabled:h.config.pwa,root:T,space_id:X,allow_zoom:ke,allow_video_trim:Fe},{allow_zoom:i=>{ke=i,we=!1;},allow_video_trim:i=>{Fe=i,we=!1;}},{})}</div></div>`:""} ${m?`${validate_component(yt,"Toast").$$render(a,{messages:m},{},{})}`:""} ${re&&ge?`${validate_component(missing_component,"svelte:component").$$render(a,{app:h,root:T},{},{})}`:""}`;while(!we);return b(),n(),v(),y(),I(),O(),Xe}),un={code:".wrap.svelte-1ogxbi0{display:flex;flex-direction:column;justify-content:center;align-items:center;margin-top:var(--size-3);background:var(--background-fill-primary);width:var(--size-full)}h2.svelte-1ogxbi0{margin-bottom:var(--size-3);color:var(--body-text-color);font-weight:var(--section-header-text-weight);font-size:var(--text-xl)}.auth.svelte-1ogxbi0{margin-top:var(--size-1);margin-bottom:var(--size-1);color:var(--body-text-color)}.creds.svelte-1ogxbi0{margin-top:var(--size-4);margin-bottom:var(--size-4);color:var(--error-text-color);font-weight:var(--weight-semibold)}",map:'{"version":3,"file":"Login.svelte","sources":["Login.svelte"],"sourcesContent":["<script lang=\\"ts\\">import Form from \\"@gradio/form\\";\\nimport { BaseTextbox as Textbox } from \\"@gradio/textbox\\";\\nimport { BaseButton } from \\"@gradio/button\\";\\nimport Column from \\"@gradio/column\\";\\nimport { Block } from \\"@gradio/atoms\\";\\nimport { _ } from \\"svelte-i18n\\";\\nexport let root;\\nexport let auth_message;\\nexport let app_mode;\\nexport let space_id;\\nlet username = \\"\\";\\nlet password = \\"\\";\\nlet incorrect_credentials = false;\\nconst submit = async () => {\\n    const formData = new FormData();\\n    formData.append(\\"username\\", username);\\n    formData.append(\\"password\\", password);\\n    let response = await fetch(root + \\"/login\\", {\\n        method: \\"POST\\",\\n        body: formData\\n    });\\n    if (response.status === 400) {\\n        incorrect_credentials = true;\\n        username = \\"\\";\\n        password = \\"\\";\\n    }\\n    else if (response.status == 200) {\\n        location.reload();\\n    }\\n};\\n<\/script>\\n\\n<div class=\\"wrap\\" class:min-h-screen={app_mode}>\\n\\t<Column variant=\\"panel\\" min_width={480}>\\n\\t\\t<h2>{$_(\\"login.login\\")}</h2>\\n\\t\\t{#if auth_message}\\n\\t\\t\\t<p class=\\"auth\\">{@html auth_message}</p>\\n\\t\\t{/if}\\n\\t\\t{#if space_id}\\n\\t\\t\\t<p class=\\"auth\\">\\n\\t\\t\\t\\t{$_(\\"login.enable_cookies\\")}\\n\\t\\t\\t</p>\\n\\t\\t{/if}\\n\\t\\t{#if incorrect_credentials}\\n\\t\\t\\t<p class=\\"creds\\">{$_(\\"login.incorrect_credentials\\")}</p>\\n\\t\\t{/if}\\n\\t\\t<Form>\\n\\t\\t\\t<Block>\\n\\t\\t\\t\\t<Textbox\\n\\t\\t\\t\\t\\tlabel={$_(\\"login.username\\")}\\n\\t\\t\\t\\t\\tlines={1}\\n\\t\\t\\t\\t\\tshow_label={true}\\n\\t\\t\\t\\t\\tmax_lines={1}\\n\\t\\t\\t\\t\\ton:submit={submit}\\n\\t\\t\\t\\t\\tbind:value={username}\\n\\t\\t\\t\\t/>\\n\\t\\t\\t</Block>\\n\\n\\t\\t\\t<Block>\\n\\t\\t\\t\\t<Textbox\\n\\t\\t\\t\\t\\tlabel={$_(\\"login.password\\")}\\n\\t\\t\\t\\t\\tlines={1}\\n\\t\\t\\t\\t\\tshow_label={true}\\n\\t\\t\\t\\t\\tmax_lines={1}\\n\\t\\t\\t\\t\\ttype=\\"password\\"\\n\\t\\t\\t\\t\\ton:submit={submit}\\n\\t\\t\\t\\t\\tbind:value={password}\\n\\t\\t\\t\\t/>\\n\\t\\t\\t</Block>\\n\\t\\t</Form>\\n\\n\\t\\t<BaseButton size=\\"lg\\" variant=\\"primary\\" on:click={submit}\\n\\t\\t\\t>{$_(\\"login.login\\")}</BaseButton\\n\\t\\t>\\n\\t</Column>\\n</div>\\n\\n<style>\\n\\t.wrap {\\n\\t\\tdisplay: flex;\\n\\t\\tflex-direction: column;\\n\\t\\tjustify-content: center;\\n\\t\\talign-items: center;\\n\\t\\tmargin-top: var(--size-3);\\n\\t\\tbackground: var(--background-fill-primary);\\n\\t\\twidth: var(--size-full);\\n\\t}\\n\\n\\th2 {\\n\\t\\tmargin-bottom: var(--size-3);\\n\\t\\tcolor: var(--body-text-color);\\n\\t\\tfont-weight: var(--section-header-text-weight);\\n\\t\\tfont-size: var(--text-xl);\\n\\t}\\n\\n\\t.auth {\\n\\t\\tmargin-top: var(--size-1);\\n\\t\\tmargin-bottom: var(--size-1);\\n\\t\\tcolor: var(--body-text-color);\\n\\t}\\n\\n\\t.creds {\\n\\t\\tmargin-top: var(--size-4);\\n\\t\\tmargin-bottom: var(--size-4);\\n\\t\\tcolor: var(--error-text-color);\\n\\t\\tfont-weight: var(--weight-semibold);\\n\\t}</style>\\n"],"names":[],"mappings":"AA8EC,oBAAM,CACL,OAAO,CAAE,IAAI,CACb,cAAc,CAAE,MAAM,CACtB,eAAe,CAAE,MAAM,CACvB,WAAW,CAAE,MAAM,CACnB,UAAU,CAAE,IAAI,QAAQ,CAAC,CACzB,UAAU,CAAE,IAAI,yBAAyB,CAAC,CAC1C,KAAK,CAAE,IAAI,WAAW,CACvB,CAEA,iBAAG,CACF,aAAa,CAAE,IAAI,QAAQ,CAAC,CAC5B,KAAK,CAAE,IAAI,iBAAiB,CAAC,CAC7B,WAAW,CAAE,IAAI,4BAA4B,CAAC,CAC9C,SAAS,CAAE,IAAI,SAAS,CACzB,CAEA,oBAAM,CACL,UAAU,CAAE,IAAI,QAAQ,CAAC,CACzB,aAAa,CAAE,IAAI,QAAQ,CAAC,CAC5B,KAAK,CAAE,IAAI,iBAAiB,CAC7B,CAEA,qBAAO,CACN,UAAU,CAAE,IAAI,QAAQ,CAAC,CACzB,aAAa,CAAE,IAAI,QAAQ,CAAC,CAC5B,KAAK,CAAE,IAAI,kBAAkB,CAAC,CAC9B,WAAW,CAAE,IAAI,iBAAiB,CACnC"}'},it=create_ssr_component((a,e,t,H)=>{let r,b;b=subscribe(xt$2,O=>r=O);let{root:p}=e,{auth_message:n}=e,{app_mode:E$1}=e,{space_id:v}=e,u="",y="";e.root===void 0&&t.root&&p!==void 0&&t.root(p),e.auth_message===void 0&&t.auth_message&&n!==void 0&&t.auth_message(n),e.app_mode===void 0&&t.app_mode&&E$1!==void 0&&t.app_mode(E$1),e.space_id===void 0&&t.space_id&&v!==void 0&&t.space_id(v),a.css.add(un);let l,I,x=a.head;do l=!0,a.head=x,I=`<div class="${["wrap svelte-1ogxbi0",E$1?"min-h-screen":""].join(" ").trim()}">${validate_component(h,"Column").$$render(a,{variant:"panel",min_width:480},{},{default:()=>`<h2 class="svelte-1ogxbi0">${escape(r("login.login"))}</h2> ${n?`<p class="auth svelte-1ogxbi0"><!-- HTML_TAG_START -->${n}<!-- HTML_TAG_END --></p>`:""} ${v?`<p class="auth svelte-1ogxbi0">${escape(r("login.enable_cookies"))}</p>`:""}  ${validate_component(s$1,"Form").$$render(a,{},{},{default:()=>`${validate_component(mt,"Block").$$render(a,{},{},{default:()=>`${validate_component(X,"Textbox").$$render(a,{label:r("login.username"),lines:1,show_label:!0,max_lines:1,value:u},{value:O=>{u=O,l=!1;}},{})}`})} ${validate_component(mt,"Block").$$render(a,{},{},{default:()=>`${validate_component(X,"Textbox").$$render(a,{label:r("login.password"),lines:1,show_label:!0,max_lines:1,type:"password",value:y},{value:O=>{y=O,l=!1;}},{})}`})}`})} ${validate_component(E,"BaseButton").$$render(a,{size:"lg",variant:"primary"},{},{default:()=>`${escape(r("login.login"))}`})}`})} </div>`;while(!l);return b(),I});async function zn({url:a,data:{server:e,port:t,local_dev_mode:H}}){let r;const b=e,p=a.searchParams.get("deep_link");try{r=await mn.connect(b,{with_null_state:!0,events:["data","log","status","render"],query_params:p?{deep_link:p}:void 0});}catch(y){const l=y.message||"";let I="";return l.includes(ns)||(I=l.replace(/^Error:?\s*/,"")),{Render:it,config:{auth_message:I,auth_required:!0,components:[],current_page:"",dependencies:[],layout:{},pages:[],page:{},root:a.origin,space_id:null,analytics_enabled:!1,connect_heartbeat:!1,css:"",js:"",theme_hash:0,head:"",dev_mode:!1,enable_queue:!1,show_error:!1,fill_height:!1,fill_width:!1,mode:"blocks",theme:"default",title:"",version:"",api_prefix:"",is_space:!1,is_colab:!1,show_api:!1,stylesheets:[],protocol:"sse_v3",username:""},api_url:b,layout:{},app:null}}if(!r.config)throw new Error("No config found");let n=r.get_url_config(a.toString());const{create_layout:E,layout:v}=Ys();await E({app:r,components:n.components,dependencies:n.dependencies,layout:n.layout,root:r.config.root+r.config.api_prefix,options:{fill_height:r.config.fill_height??!1}});const u=get_store_value(v);return await oa(),{Render:r.config?.auth_required?it:pn,config:n,api_url:b,layout:u,app:r}}

var _page_ts = /*#__PURE__*/Object.freeze({
	__proto__: null,
	load: zn
});

const a=s$2,t=a$2;

async function s({request:o}){const e=o.headers.get("x-gradio-server")||"http://127.0.0.1:7860",r=o.headers.get("x-gradio-port")||"7860",d=o.headers.get("x-gradio-local-dev-mode")||t?"true":void 0;return {server:e,port:r,local_dev_mode:d}}

var _page_server_ts = /*#__PURE__*/Object.freeze({
	__proto__: null,
	load: s
});

const index = 2;
let component_cache;
const component = async () => component_cache ??= (await import('./_page.svelte-Bwyw3w3H.js')).default;
const universal_id = "src/routes/[...catchall]/+page.ts";
const server_id = "src/routes/[...catchall]/+page.server.ts";
const imports = ["_app/immutable/nodes/2.BhLnEMeX.js","_app/immutable/chunks/2.DPLbyeoY.js","_app/immutable/chunks/preload-helper.D6kgxu3v.js","_app/immutable/chunks/stores.CuZyOi6d.js","_app/immutable/chunks/client.--7n92yq.js"];
const stylesheets = ["_app/immutable/assets/2.BFAvMnlG.css","_app/immutable/assets/Index.C5NYahSl.css","_app/immutable/assets/Index.E3yBBMTH.css","_app/immutable/assets/AudioPlayer.D5BS3Cgh.css","_app/immutable/assets/Example.D7K5RtQ2.css","_app/immutable/assets/InteractiveAudio.B76TQFG-.css","_app/immutable/assets/Upload.L7mprsyN.css","_app/immutable/assets/Index.CSHIljo_.css","_app/immutable/assets/Checkbox.COx9d1js.css","_app/immutable/assets/Index.DMKGW8pW.css","_app/immutable/assets/Example.oomIF0ca.css","_app/immutable/assets/Code.DloLYeAi.css","_app/immutable/assets/Example.Bw8Q_3wB.css","_app/immutable/assets/Index.DwWu86Nh.css","_app/immutable/assets/Example.1kVNej19.css","_app/immutable/assets/Index.mRQMY0Jj.css","_app/immutable/assets/ImageUploader.DMdYP1a9.css","_app/immutable/assets/Example.DikqVAPo.css","_app/immutable/assets/Index.D3f6Hf9S.css","_app/immutable/assets/Index.Bk5ZTHOI.css","_app/immutable/assets/Index.Bd2aUp3T.css","_app/immutable/assets/Dropdown.CWxB-qJp.css","_app/immutable/assets/Index.tcNSQSor.css","_app/immutable/assets/Index.CIMAvdMc.css","_app/immutable/assets/Example.DpWs9cEC.css","_app/immutable/assets/FileUpload.b2Zdge9M.css","_app/immutable/assets/Example.DfhEULNF.css","_app/immutable/assets/Index.BKaa_GXG.css","_app/immutable/assets/Gallery.CUVAWrOv.css","_app/immutable/assets/Video.DJw86Ppo.css","_app/immutable/assets/Index.Cgj6KPvj.css","_app/immutable/assets/Index.KsvjhaTn.css","_app/immutable/assets/Index.Csm0OGa9.css","_app/immutable/assets/Example.CSw4pLi5.css","_app/immutable/assets/Example.6rv12T44.css","_app/immutable/assets/Index.CCAzyDPy.css","_app/immutable/assets/Example.fMB4cHw6.css","_app/immutable/assets/Index.xkmfPIkL.css","_app/immutable/assets/Example.CG7uBGLE.css","_app/immutable/assets/JSON.AVFPpFex.css","_app/immutable/assets/Index.D3BKJl5I.css","_app/immutable/assets/Index.BTXaMQgd.css","_app/immutable/assets/Index.Be3F7oKw.css","_app/immutable/assets/Example.CCTTJ5R1.css","_app/immutable/assets/Index.D6bhueJw.css","_app/immutable/assets/Index.WdTVQ0oj.css","_app/immutable/assets/Index.Dclo02rM.css","_app/immutable/assets/Index.DkzrJAuX.css","_app/immutable/assets/BokehPlot.Cd-I2ErV.css","_app/immutable/assets/AltairPlot.CSe9xcFj.css","_app/immutable/assets/MatplotlibPlot.AF_QcUtc.css","_app/immutable/assets/Index.-UpFQsHg.css","_app/immutable/assets/Index.CfowPFmo.css","_app/immutable/assets/Index.w1Ra_uQ1.css","_app/immutable/assets/Index.Cwr2RydD.css","_app/immutable/assets/Index.C0mowOU5.css","_app/immutable/assets/Index.Gmwqb-vD.css","_app/immutable/assets/Tabs.C0qLuAtA.css","_app/immutable/assets/Index.DYDmCduo.css","_app/immutable/assets/Index.CQqQuB-Q.css","_app/immutable/assets/VideoPreview.BeECudjn.css","_app/immutable/assets/Example.B5CSTz0f.css","_app/immutable/assets/index.CFBZQE_H.css","_app/immutable/assets/Index.CgDrEMlk.css","_app/immutable/assets/ApiDocs.CrTYCJN9.css","_app/immutable/assets/ApiRecorder.7UmvbTxs.css","_app/immutable/assets/Settings.D01KD214.css"];
const fonts = [];

var _2 = /*#__PURE__*/Object.freeze({
	__proto__: null,
	component: component,
	fonts: fonts,
	imports: imports,
	index: index,
	server: _page_server_ts,
	server_id: server_id,
	stylesheets: stylesheets,
	universal: _page_ts,
	universal_id: universal_id
});

export { yt$1 as $, A, b as B, C, Do as D, Et as E, An as F, Zt as G, qt as H, Ir$1 as I, Be as J, Ks as K, Lt as L, ve as M, xt as N, X$1 as O, h$1 as P, _t as Q, Rt as R, St as S, Tt as T, Uo as U, w$1 as V, We as W, Xs as X, Ys as Y, Zs as Z, _, aa as a, ne as a0, re as a1, Qt as a2, he as a3, me as a4, we as a5, fe as a6, Le$1 as a7, be as a8, la as a9, lt$2 as aA, Qs as aB, now as aC, loop as aD, is_date as aE, _2 as aF, jt as aa, f$1 as ab, st$1 as ac, de as ad, Wt as ae, zt as af, Vt as ag, Ae as ah, ae as ai, se as aj, E as ak, Y as al, ce as am, globals as an, ea as ao, Js as ap, y as aq, Ke$2 as ar, Nt as as, Jt as at, Ne$1 as au, pe as av, oe as aw, At as ax, te$2 as ay, le as az, rt as b, bt as c, a as d, bt$1 as e, Xt$1 as f, kt as g, h, ia as i, Ke as j, ko as k, j as l, mt as m, na as n, oa as o, Ut as p, qe as q, ra as r, sa as s, te as t, qs as u, Kt as v, ot$1 as w, Ce as x, yt as y, ze as z };
//# sourceMappingURL=2-CPfSxV2Q.js.map
