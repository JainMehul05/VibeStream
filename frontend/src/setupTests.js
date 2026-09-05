// jest-dom adds custom jest matchers for asserting on DOM nodes.
// allows you to do things like:
// expect(element).toHaveTextContent(/react/i)
// learn more: https://github.com/testing-library/jest-dom
import "@testing-library/jest-dom";

// Mock navigator properties used by detectTier
Object.defineProperty(navigator, "hardwareConcurrency", {
  value: 8,
  configurable: true,
});

Object.defineProperty(navigator, "deviceMemory", {
  value: 8,
  configurable: true,
});

Object.defineProperty(navigator, "userAgent", {
  value: "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
  configurable: true,
});

// Mock window.matchMedia for prefers-reduced-motion
window.matchMedia = jest.fn().mockImplementation((query) => ({
  matches: false,
  media: query,
  onchange: null,
  addListener: jest.fn(),
  removeListener: jest.fn(),
  addEventListener: jest.fn(),
  removeEventListener: jest.fn(),
  dispatchEvent: jest.fn(),
}));

// Mock window.innerWidth and innerHeight
Object.defineProperty(window, "innerWidth", {
  value: 1920,
  configurable: true,
});

Object.defineProperty(window, "innerHeight", {
  value: 1080,
  configurable: true,
});

// Mock document.documentElement.scrollHeight and clientHeight for scroll calculations
Object.defineProperty(document.documentElement, "scrollHeight", {
  value: 2000,
  configurable: true,
});

Object.defineProperty(document.documentElement, "clientHeight", {
  value: 1080,
  configurable: true,
});

Object.defineProperty(document.documentElement, "scrollTop", {
  value: 0,
  configurable: true,
  writable: true,
});