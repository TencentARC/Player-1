package net.minecraft.client;

import com.microsoft.Malmo.Schemas.AgentSection;
import com.microsoft.Malmo.Schemas.MissionInit;
import com.microsoft.Malmo.Schemas.VideoProducer;
import net.minecraft.client.settings.PointOfView;

import java.util.ArrayList;
import java.util.Collection;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Set;

import net.minecraft.client.util.InputMappings;

/** Executes MineStudio keyboard, mouse and mission viewpoint controls. */
public final class PlayerOneInputBridge {
    public static final int HELD = 1;
    public static final int IMPULSE = 2;

    private static final double CAMERA_SCALE = 6.666666666666667D;
    private static final double ABSOLUTE_POINTER_OFFSET = 10000.0D;
    private static final double NORMALIZED_POINTER_LIMIT = 1000.0D;

    private PlayerOneInputBridge() {}

    /** Applies the mission's absolute camera viewpoint on every environment reset. */
    public static void applyMissionViewpoint(MissionInit missionInit) {
        AgentSection agent = missionInit.getMission().getAgentSection().get(0);
        for (Object handler : agent.getAgentHandlers().getAgentMissionHandlers()) {
            if (handler instanceof VideoProducer) {
                int viewpoint = ((VideoProducer) handler).getViewpoint();
                PointOfView[] values = PointOfView.values();
                if (viewpoint < 0 || viewpoint >= values.length) {
                    throw new IllegalArgumentException("invalid mission viewpoint: " + viewpoint);
                }
                Minecraft.getInstance().gameSettings.setPointOfView(values[viewpoint]);
                return;
            }
        }
        throw new IllegalStateException("mission is missing its VideoProducer viewpoint");
    }

    public static KeyboardListener.State constructKeyboardState(String actions) {
        Set<String> keys = new LinkedHashSet<String>();
        Set<String> newKeys = new LinkedHashSet<String>();
        for (String action : actions.split("\n")) {
            String[] parts = split(action);
            if (parts.length <= 1 || isNonKeyboardAction(parts[0])) {
                continue;
            }
            String key = actionToKey(parts[0]);
            if (key == null) {
                continue;
            }
            int value = Integer.parseInt(parts[1]);
            if (value == HELD) {
                keys.add(key);
            } else if (value == IMPULSE) {
                newKeys.add(key);
            }
        }
        return new KeyboardListener.State(keys, newKeys, "");
    }

    public static MouseHelper.State constructMouseState(String actions) {
        double x = 0.0D;
        double y = 0.0D;
        double dx = 0.0D;
        double dy = 0.0D;
        double dwheel = 0.0D;
        List<Integer> buttons = new ArrayList<Integer>();
        List<Integer> newButtons = new ArrayList<Integer>();
        for (String action : actions.split("\n")) {
            String[] parts = split(action);
            if (parts[0].equals("camera")) {
                double cameraY = Double.parseDouble(parts[1]);
                double cameraX = Double.parseDouble(parts[2]);
                if (isAbsolutePointerWire(cameraX, cameraY)) {
                    x = cameraX;
                    y = cameraY;
                } else {
                    dx = cameraX * CAMERA_SCALE;
                    dy = cameraY * CAMERA_SCALE;
                }
                continue;
            }
            if (parts[0].equals("dwheel")) {
                dwheel = Double.parseDouble(parts[1]);
                continue;
            }
            if (parts.length <= 1 || isNonMouseAction(parts[0])) {
                continue;
            }
            Integer button = actionToMouseButton(parts[0]);
            if (button == null) {
                continue;
            }
            int value = Integer.parseInt(parts[1]);
            if (value == HELD) {
                buttons.add(button);
            } else if (value == IMPULSE) {
                newButtons.add(button);
            }
        }
        return new MouseHelper.State(x, y, dx, dy, dwheel, buttons, newButtons);
    }

    public static void execMouseMove(MouseHelper.State state) {
        Minecraft minecraft = Minecraft.getInstance();
        MouseHelper mouse = minecraft.mouseHelper;
        MainWindow window = minecraft.getMainWindow();
        double x;
        double y;

        if (isAbsolutePointerWire(state.x, state.y)) {
            if (minecraft.currentScreen == null) {
                return;
            }
            double normalizedX = state.x - ABSOLUTE_POINTER_OFFSET;
            double normalizedY = state.y - ABSOLUTE_POINTER_OFFSET;
            x = normalizedX / NORMALIZED_POINTER_LIMIT * Math.max(0, window.getWidth() - 1);
            y = normalizedY / NORMALIZED_POINTER_LIMIT * Math.max(0, window.getHeight() - 1);
        } else {
            if (state.dx == 0.0D && state.dy == 0.0D) {
                return;
            }
            double scale = mouse.getScaleFactor();
            x = mouse.getMouseX() + state.dx * scale;
            y = mouse.getMouseY() + state.dy * scale;
            if (minecraft.currentScreen != null) {
                x = clip(x, 0.0D, window.getWidth());
                y = clip(y, 0.0D, window.getHeight());
            }
        }
        mouse.cursorPosCallbackImpl(x, y);
    }

    public static void execKeyboardImpulses(KeyboardListener.State state) {
        Minecraft minecraft = Minecraft.getInstance();
        Set<String> impulses = new LinkedHashSet<String>(state.newKeys);
        impulses.removeAll(state.keys);
        int modifiers = getModifiers(state.keys, impulses);
        for (String key : impulses) {
            if (key.equals("key.keyboard.escape")
                    && minecraft.currentScreen == null
                    && minecraft.gameSettings.envPort != 0) {
                continue;
            }
            InputMappings.Input input = InputMappings.getInputByName(key);
            minecraft.keyboardListener.onKeyEventImpl(input.getKeyCode(), 0, 1, modifiers);
            minecraft.keyboardListener.onKeyEventImpl(input.getKeyCode(), 0, 0, modifiers);
        }
        minecraft.keyboardListener.getState();
    }

    public static void execMouseImpulses(MouseHelper.State state, int modifiers) {
        Minecraft minecraft = Minecraft.getInstance();
        Set<Integer> impulses = new LinkedHashSet<Integer>(state.newButtons);
        impulses.removeAll(state.buttons);
        long window = minecraft.getMainWindow().getHandle();
        for (Integer button : impulses) {
            minecraft.mouseHelper.mouseButtonCallbackImpl(window, button.intValue(), 1, modifiers);
            minecraft.mouseHelper.mouseButtonCallbackImpl(window, button.intValue(), 0, modifiers);
        }
        minecraft.mouseHelper.getState();
    }

    private static String[] split(String action) {
        String stripped = action.trim();
        return stripped.isEmpty() ? new String[] {""} : stripped.split("\\s+");
    }

    private static boolean isAbsolutePointerWire(double x, double y) {
        double maximum = ABSOLUTE_POINTER_OFFSET + NORMALIZED_POINTER_LIMIT;
        return x >= ABSOLUTE_POINTER_OFFSET
                && x <= maximum
                && y >= ABSOLUTE_POINTER_OFFSET
                && y <= maximum;
    }

    private static double clip(double value, double minimum, double maximum) {
        return Math.min(Math.max(value, minimum), maximum);
    }

    private static boolean isNonKeyboardAction(String action) {
        return action.equals("camera")
                || action.equals("dwheel")
                || action.equals("chat")
                || action.equals("voxels")
                || action.equals("mobs")
                || action.equals("equip");
    }

    private static boolean isNonMouseAction(String action) {
        return action.equals("chat") || action.equals("voxels") || action.equals("mobs");
    }

    private static Integer actionToMouseButton(String action) {
        if (action.equals("attack")) {
            return Integer.valueOf(0);
        }
        if (action.equals("use")) {
            return Integer.valueOf(1);
        }
        if (action.equals("pickItem")) {
            return Integer.valueOf(2);
        }
        return null;
    }

    private static String actionToKey(String action) {
        if (action.equals("forward")) {
            return "key.keyboard.w";
        }
        if (action.equals("back")) {
            return "key.keyboard.s";
        }
        if (action.equals("left")) {
            return "key.keyboard.a";
        }
        if (action.equals("right")) {
            return "key.keyboard.d";
        }
        if (action.equals("jump")) {
            return "key.keyboard.space";
        }
        if (action.equals("sprint")) {
            return "key.keyboard.left.control";
        }
        if (action.equals("sneak")) {
            return "key.keyboard.left.shift";
        }
        if (action.startsWith("hotbar.")) {
            return "key.keyboard." + action.substring("hotbar.".length());
        }
        if (action.equals("inventory")) {
            return "key.keyboard.e";
        }
        if (action.equals("drop")) {
            return "key.keyboard.q";
        }
        if (action.equals("swapHands")) {
            return "key.keyboard.f";
        }
        if (action.equals("togglePerspective")) {
            return "key.keyboard.f5";
        }
        if (action.equals("ESC")) {
            return "key.keyboard.escape";
        }
        return null;
    }

    private static int getModifiers(Collection<String> held, Collection<String> impulses) {
        if (held.contains("key.keyboard.left.shift")
                || held.contains("key.keyboard.right.shift")
                || impulses.contains("key.keyboard.left.shift")
                || impulses.contains("key.keyboard.right.shift")) {
            return 1;
        }
        return 0;
    }
}
