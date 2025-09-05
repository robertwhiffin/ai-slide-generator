import { s as Gp, t as m, f as um, c as Yy, p as qy, S as Et } from './Index16-BKwrbaLU.js';
import { yaml as a } from './yaml-C6fZICTl.js';
import './ssr-C3HYbsxA.js';
import './2-CPfSxV2Q.js';
import './index-ClteBeTX.js';
import './Component-NmRBwSfF.js';
import 'path';
import 'url';
import 'fs';
import './Example7-BgAxc6bX.js';

const n=/^---\s*$/m,F={defineNodes:[{name:"Frontmatter",block:!0},"FrontmatterMark"],props:[Gp({Frontmatter:[m.documentMeta,m.monospace],FrontmatterMark:m.processingInstruction}),um.add({Frontmatter:Yy,FrontmatterMark:()=>null})],wrap:qy(t=>{const{parser:e}=Et.define(a);return t.type.name==="Frontmatter"?{parser:e,overlay:[{from:t.from+4,to:t.to-4}]}:null}),parseBlock:[{name:"Frontmatter",before:"HorizontalRule",parse:(t,e)=>{let r;const a=new Array;if(t.lineStart===0&&n.test(e.text)){for(a.push(t.elt("FrontmatterMark",0,4));t.nextLine();)if(n.test(e.text)){r=t.lineStart+4;break}return r!==void 0&&(a.push(t.elt("FrontmatterMark",r-4,r)),t.addElement(t.elt("Frontmatter",0,r,a))),!0}return !1}}]};

export { F as frontmatter };
//# sourceMappingURL=frontmatter-ChqJ88l6.js.map
