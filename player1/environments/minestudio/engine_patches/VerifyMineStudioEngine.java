import net.minecraft.client.KeyboardListener;
import net.minecraft.client.PlayerOneInputBridge;

/** Build-time input contract checks for the patched engine. */
public final class VerifyMineStudioEngine {
    private VerifyMineStudioEngine() {}

    public static void main(String[] args) {
        String[] commands = {"forward", "back", "left", "right", "jump", "sprint", "sneak",
                "inventory", "drop", "swapHands", "ESC", "togglePerspective"};
        String[] keys = {"w", "s", "a", "d", "space", "left.control", "left.shift",
                "e", "q", "f", "escape", "f5"};
        for (int i = 0; i < commands.length; i++) {
            checkKey(commands[i], "key.keyboard." + keys[i]);
        }
        for (int slot = 1; slot <= 9; slot++) {
            checkKey("hotbar." + slot, "key.keyboard." + slot);
        }
        KeyboardListener.State empty = PlayerOneInputBridge.constructKeyboardState("");
        require(empty.keys.isEmpty() && empty.newKeys.isEmpty(), "keyboard input persisted across steps");
    }

    private static void checkKey(String command, String key) {
        KeyboardListener.State held = PlayerOneInputBridge.constructKeyboardState(command + " 1");
        KeyboardListener.State tapped = PlayerOneInputBridge.constructKeyboardState(command + " 2");
        KeyboardListener.State released = PlayerOneInputBridge.constructKeyboardState(command + " 0");
        require(held.keys.contains(key) && !held.newKeys.contains(key), command + " hold changed");
        require(tapped.newKeys.contains(key) && !tapped.keys.contains(key), command + " impulse changed");
        require(released.keys.isEmpty() && released.newKeys.isEmpty(), command + " release changed");
    }

    private static void require(boolean condition, String message) {
        if (!condition) {
            throw new IllegalStateException(message);
        }
    }
}
