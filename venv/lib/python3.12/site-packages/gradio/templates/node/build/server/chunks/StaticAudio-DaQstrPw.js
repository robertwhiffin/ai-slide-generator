import { c as create_ssr_component, b as createEventDispatcher, v as validate_component } from './ssr-C3HYbsxA.js';
import { e as bt, t as te, W as We, C, l as j, p as Ut, z as ze, _, g as kt } from './2-CPfSxV2Q.js';
import { Y as Yt } from './AudioPlayer-DDXFIunE.js';
import './index-ClteBeTX.js';
import './Component-NmRBwSfF.js';
import 'path';
import 'url';
import 'fs';
import './hls-DpKhbIaL.js';

const q=create_ssr_component((a,o,e,M)=>{let{value:t=null}=o,{label:_$1}=o,{show_label:d=!0}=o,{show_download_button:i=!0}=o,{show_share_button:u=!1}=o,{i18n:r}=o,{waveform_settings:n={}}=o,{waveform_options:f={show_recording_waveform:!0}}=o,{editable:c=!0}=o,{loop:v}=o,{display_icon_button_wrapper_top_corner:w=!1}=o;const s=createEventDispatcher();return o.value===void 0&&e.value&&t!==void 0&&e.value(t),o.label===void 0&&e.label&&_$1!==void 0&&e.label(_$1),o.show_label===void 0&&e.show_label&&d!==void 0&&e.show_label(d),o.show_download_button===void 0&&e.show_download_button&&i!==void 0&&e.show_download_button(i),o.show_share_button===void 0&&e.show_share_button&&u!==void 0&&e.show_share_button(u),o.i18n===void 0&&e.i18n&&r!==void 0&&e.i18n(r),o.waveform_settings===void 0&&e.waveform_settings&&n!==void 0&&e.waveform_settings(n),o.waveform_options===void 0&&e.waveform_options&&f!==void 0&&e.waveform_options(f),o.editable===void 0&&e.editable&&c!==void 0&&e.editable(c),o.loop===void 0&&e.loop&&v!==void 0&&e.loop(v),o.display_icon_button_wrapper_top_corner===void 0&&e.display_icon_button_wrapper_top_corner&&w!==void 0&&e.display_icon_button_wrapper_top_corner(w),t&&s("change",t),`${validate_component(bt,"BlockLabel").$$render(a,{show_label:d,Icon:te,float:!1,label:_$1||r("audio.audio")},{},{})} ${t!==null?`${validate_component(We,"IconButtonWrapper").$$render(a,{display_top_corner:w},{},{default:()=>`${i?`${validate_component(C,"DownloadLink").$$render(a,{href:t.is_stream?t.url?.replace("playlist.m3u8","playlist-file"):t.url,download:t.orig_name||t.path},{},{default:()=>`${validate_component(j,"IconButton").$$render(a,{Icon:Ut,label:r("common.download")},{},{})}`})}`:""} ${u?`${validate_component(ze,"ShareButton").$$render(a,{i18n:r,formatter:async m=>m?`<audio controls src="${await _(m.url)}"></audio>`:"",value:t},{},{})}`:""}`})} ${validate_component(Yt,"AudioPlayer").$$render(a,{value:t,label:_$1,i18n:r,waveform_settings:n,waveform_options:f,editable:c,loop:v},{},{})}`:`${validate_component(kt,"Empty").$$render(a,{size:"small"},{},{default:()=>`${validate_component(te,"Music").$$render(a,{},{},{})}`})}`}`});

export { q as default };
//# sourceMappingURL=StaticAudio-DaQstrPw.js.map
