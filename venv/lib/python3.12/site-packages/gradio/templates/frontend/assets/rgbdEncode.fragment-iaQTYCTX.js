import{j as r}from"./index-BoSc34Ms.js";import"./helperFunctions-CjxGC5Ut.js";import"./index-6iIxEka4.js";import"./svelte/svelte.js";const e="rgbdEncodePixelShader",o=`varying vec2 vUV;uniform sampler2D textureSampler;
#include<helperFunctions>
#define CUSTOM_FRAGMENT_DEFINITIONS
void main(void) 
{gl_FragColor=toRGBD(texture2D(textureSampler,vUV).rgb);}`;r.ShadersStore[e]||(r.ShadersStore[e]=o);const n={name:e,shader:o};export{n as rgbdEncodePixelShader};
//# sourceMappingURL=rgbdEncode.fragment-iaQTYCTX.js.map
