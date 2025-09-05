import { c as create_ssr_component, d as add_attribute } from './ssr-C3HYbsxA.js';
import { A } from './2-CPfSxV2Q.js';
import './index-ClteBeTX.js';
import './Component-NmRBwSfF.js';
import 'path';
import 'url';
import 'fs';

const B=create_ssr_component((L,a,e,S)=>{let r,{value:s}=a,{display_mode:c}=a,{clear_color:_}=a,{camera_position:m}=a,{zoom_speed:v}=a,{pan_speed:f}=a,{resolved_url:d=void 0}=a,w,y,u;function n(t,o,I){const l=u.camera;t[0]!==null&&(l.alpha=t[0]*Math.PI/180),t[1]!==null&&(l.beta=t[1]*Math.PI/180),t[2]!==null&&(l.radius=t[2]),l.lowerRadiusLimit=.1;const R=()=>{l.wheelPrecision=250/(l.radius*o),l.panningSensibility=1e4*I/l.radius;};R(),l.onAfterCheckInputsObservable.add(R);}function M(){}if(a.value===void 0&&e.value&&s!==void 0&&e.value(s),a.display_mode===void 0&&e.display_mode&&c!==void 0&&e.display_mode(c),a.clear_color===void 0&&e.clear_color&&_!==void 0&&e.clear_color(_),a.camera_position===void 0&&e.camera_position&&m!==void 0&&e.camera_position(m),a.zoom_speed===void 0&&e.zoom_speed&&v!==void 0&&e.zoom_speed(v),a.pan_speed===void 0&&e.pan_speed&&f!==void 0&&e.pan_speed(f),a.resolved_url===void 0&&e.resolved_url&&d!==void 0&&e.resolved_url(d),a.update_camera===void 0&&e.update_camera&&n!==void 0&&e.update_camera(n),a.reset_camera_position===void 0&&e.reset_camera_position&&M!==void 0&&e.reset_camera_position(M),r=s.url,d=r,r){w=r;const t=r;A(r).then(o=>{w===t?d=o??void 0:o&&URL.revokeObjectURL(o);});}return `<canvas${add_attribute("this",y,0)}></canvas>`});

export { B as default };
//# sourceMappingURL=Canvas3D-CbtzrR-f.js.map
