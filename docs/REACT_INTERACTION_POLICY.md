# React interaction policy

ComicPile's React UI must use visible, conventional controls for user actions.

Custom swipe interactions, horizontal gesture recognizers, hidden gesture-revealed actions, and long-press-only actions are prohibited. Every action must remain discoverable and operable with touch, mouse, keyboard, and assistive technology without gesture arbitration or delayed click handling.

Action availability must not depend on a gesture that has no equivalent visible control.

Native browser scrolling and established drag-and-drop reordering are not custom action gestures and remain supported where already implemented.
