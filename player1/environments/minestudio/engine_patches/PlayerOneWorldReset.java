package com.minerl.multiagent.env;

import net.minecraft.client.Minecraft;
import net.minecraft.server.integrated.IntegratedServer;

/** Releases MineRL's previous integrated server before creating another world. */
public final class PlayerOneWorldReset {
    private PlayerOneWorldReset() {}

    public static void closePreviousServer(Minecraft minecraft) {
        IntegratedServer server = minecraft.getIntegratedServer();
        if (server != null) {
            server.initiateShutdown(false);
            try {
                server.close();
            } finally {
                server.getSnooper().stop();
            }
        }
    }

    public static void closePreviousWorld(Minecraft minecraft) {
        closePreviousServer(minecraft);
        minecraft.unloadWorld();
    }
}
