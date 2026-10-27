// Preact + hooks + htm, so views can write `html\`<div>...</div>\`` without a build step.
import { h, render, Fragment, createContext, cloneElement, toChildArray, createRef } from 'preact';
import {
  useState, useEffect, useLayoutEffect, useRef, useMemo, useCallback, useContext, useReducer, useId,
} from 'preact/hooks';
import htm from 'htm';

export const html = htm.bind(h);

export {
  h, render, Fragment, createContext, cloneElement, toChildArray, createRef,
  useState, useEffect, useLayoutEffect, useRef, useMemo, useCallback, useContext, useReducer, useId,
};
