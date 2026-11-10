import java.io.InputStream;
import java.net.URI;
import java.nio.file.FileSystem;
import java.nio.file.FileSystems;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.nio.file.StandardCopyOption;
import java.nio.file.attribute.BasicFileAttributeView;
import java.nio.file.attribute.FileTime;
import java.nio.charset.StandardCharsets;
import java.util.Collections;
import java.util.function.Function;

import org.objectweb.asm.ClassReader;
import org.objectweb.asm.ClassWriter;
import org.objectweb.asm.Opcodes;
import org.objectweb.asm.tree.AbstractInsnNode;
import org.objectweb.asm.tree.ClassNode;
import org.objectweb.asm.tree.InsnNode;
import org.objectweb.asm.tree.InsnList;
import org.objectweb.asm.tree.MethodInsnNode;
import org.objectweb.asm.tree.MethodNode;
import org.objectweb.asm.tree.VarInsnNode;

/** Applies Player-1 JVM reuse, world reset, input and viewpoint support to the upstream engine. */
public final class PatchMineStudioEngine {
    private static final String ENV_SERVER = "/com/minerl/multiagent/env/EnvServer.class";
    private static final String REPLAY_SENDER = "/net/minecraft/client/ReplaySender.class";
    private static final String BIOME = "/net/minecraft/world/biome/Biome.class";
    private static final String RESET_HELPER = "com/minerl/multiagent/env/PlayerOneWorldReset";
    private static final String RESET_HELPER_ENTRY = "/" + RESET_HELPER + ".class";
    private static final String INPUT_HELPER = "net/minecraft/client/PlayerOneInputBridge";
    private static final String INPUT_HELPER_ENTRY = "/" + INPUT_HELPER + ".class";
    private static final String INPUT_MARKER_ENTRY = "/META-INF/gamegym-minestudio-input-v3";
    private static final byte[] INPUT_MARKER =
            "mllm_game_agent_minestudio_input_v3\n".getBytes(StandardCharsets.UTF_8);
    private static final String MINECRAFT_DESCRIPTOR = "(Lnet/minecraft/client/Minecraft;)V";
    private static final FileTime GENERATED_ENTRY_TIME = FileTime.fromMillis(315532800000L);

    private PatchMineStudioEngine() {}

    public static void main(String[] args) throws Exception {
        if (args.length != 2) {
            throw new IllegalArgumentException("usage: PatchMineStudioEngine INPUT_JAR OUTPUT_JAR");
        }
        Path input = Paths.get(args[0]).toAbsolutePath().normalize();
        Path output = Paths.get(args[1]).toAbsolutePath().normalize();
        if (input.equals(output)) {
            throw new IllegalArgumentException("input and output JAR paths must differ");
        }
        Files.createDirectories(output.getParent());
        Files.copy(input, output, StandardCopyOption.COPY_ATTRIBUTES);

        URI jarUri = URI.create("jar:" + output.toUri());
        try (FileSystem jar = FileSystems.newFileSystem(
                jarUri, Collections.singletonMap("create", "false"))) {
            rewrite(jar, ENV_SERVER, PatchMineStudioEngine::patchEnvServer);
            rewrite(jar, REPLAY_SENDER, PatchMineStudioEngine::patchReplaySender);
            rewrite(jar, BIOME, PatchMineStudioEngine::patchBiomeTemperatureCache);

            copyClass(jar, RESET_HELPER_ENTRY);
            copyClass(jar, INPUT_HELPER_ENTRY);
            Path markerPath = jar.getPath(INPUT_MARKER_ENTRY);
            Files.createDirectories(markerPath.getParent());
            Files.write(markerPath, INPUT_MARKER);
            setGeneratedTime(markerPath);
        }
    }

    private static void copyClass(FileSystem jar, String entry) throws Exception {
        Path path = jar.getPath(entry);
        Files.createDirectories(path.getParent());
        try (InputStream source = PatchMineStudioEngine.class
                .getClassLoader()
                .getResourceAsStream(entry.substring(1))) {
            if (source == null) {
                throw new IllegalStateException("compiled helper not found: " + entry);
            }
            Files.copy(source, path);
        }
        setGeneratedTime(path);
    }

    private static void setGeneratedTime(Path path) throws Exception {
        Files.getFileAttributeView(path, BasicFileAttributeView.class)
                .setTimes(GENERATED_ENTRY_TIME, GENERATED_ENTRY_TIME, GENERATED_ENTRY_TIME);
    }

    private static void rewrite(
            FileSystem jar, String entry, Function<byte[], byte[]> patch) throws Exception {
        Path path = jar.getPath(entry);
        FileTime timestamp = Files.getLastModifiedTime(path);
        Files.write(path, patch.apply(Files.readAllBytes(path)));
        Files.setLastModifiedTime(path, timestamp);
    }

    private static ClassNode readClass(byte[] bytecode) {
        ClassNode classNode = new ClassNode();
        new ClassReader(bytecode).accept(classNode, 0);
        return classNode;
    }

    private static byte[] writeClass(ClassNode classNode) {
        ClassWriter writer = new ClassWriter(0);
        classNode.accept(writer);
        return writer.toByteArray();
    }

    private static MethodNode method(ClassNode classNode, String name, String descriptor) {
        for (MethodNode method : classNode.methods) {
            if (method.name.equals(name) && method.desc.equals(descriptor)) {
                return method;
            }
        }
        throw new IllegalStateException("method not found: " + name + descriptor);
    }

    static byte[] patchEnvServer(byte[] original) {
        ClassNode classNode = readClass(original);
        MethodNode target = method(
                classNode,
                "createNewWorld",
                "(Lcom/microsoft/Malmo/Schemas/MissionInit;Ljava/lang/Long;)V");
        AbstractInsnNode insertionPoint = target.instructions.getFirst();
        while (insertionPoint != null) {
            if (insertionPoint instanceof VarInsnNode) {
                VarInsnNode variable = (VarInsnNode) insertionPoint;
                if (variable.getOpcode() == Opcodes.ASTORE && variable.var == 3) {
                    break;
                }
            }
            insertionPoint = insertionPoint.getNext();
        }
        target.instructions.insert(
                insertionPoint,
                new MethodInsnNode(
                        Opcodes.INVOKESTATIC,
                        RESET_HELPER,
                        "closePreviousWorld",
                        MINECRAFT_DESCRIPTOR,
                        false));
        target.instructions.insert(insertionPoint, new VarInsnNode(Opcodes.ALOAD, 3));
        target.maxStack = Math.max(target.maxStack, 1);
        replaceWithStaticDelegate(
                method(
                        classNode,
                        "constructKeyboardState",
                        "(Ljava/lang/String;)Lnet/minecraft/client/KeyboardListener$State;"),
                "constructKeyboardState",
                "(Ljava/lang/String;)Lnet/minecraft/client/KeyboardListener$State;");
        replaceWithStaticDelegate(
                method(
                        classNode,
                        "constructMouseState",
                        "(Ljava/lang/String;)Lnet/minecraft/client/MouseHelper$State;"),
                "constructMouseState",
                "(Ljava/lang/String;)Lnet/minecraft/client/MouseHelper$State;");
        patchMissionViewpoint(method(
                classNode,
                "setGameSetttings",
                "(Lcom/microsoft/Malmo/Schemas/MissionInit;)V"));
        return writeClass(classNode);
    }

    private static void patchMissionViewpoint(MethodNode target) {
        int hooks = 0;
        for (AbstractInsnNode instruction = target.instructions.getFirst();
                instruction != null;
                instruction = instruction.getNext()) {
            if (instruction.getOpcode() != Opcodes.RETURN) {
                continue;
            }
            InsnList hook = new InsnList();
            hook.add(new VarInsnNode(Opcodes.ALOAD, 1));
            hook.add(new MethodInsnNode(
                    Opcodes.INVOKESTATIC,
                    INPUT_HELPER,
                    "applyMissionViewpoint",
                    "(Lcom/microsoft/Malmo/Schemas/MissionInit;)V",
                    false));
            target.instructions.insertBefore(instruction, hook);
            hooks += 1;
        }
        if (hooks != 1) {
            throw new IllegalStateException("expected one setGameSetttings return, found " + hooks);
        }
        target.maxStack = Math.max(target.maxStack, 1);
    }

    private static void replaceWithStaticDelegate(
            MethodNode target, String helperMethod, String descriptor) {
        target.instructions.clear();
        target.instructions.add(new VarInsnNode(Opcodes.ALOAD, 0));
        target.instructions.add(
                new MethodInsnNode(
                        Opcodes.INVOKESTATIC,
                        INPUT_HELPER,
                        helperMethod,
                        descriptor,
                        false));
        target.instructions.add(new InsnNode(Opcodes.ARETURN));
        target.tryCatchBlocks.clear();
        if (target.localVariables != null) {
            target.localVariables.clear();
        }
        if (target.visibleLocalVariableAnnotations != null) {
            target.visibleLocalVariableAnnotations.clear();
        }
        if (target.invisibleLocalVariableAnnotations != null) {
            target.invisibleLocalVariableAnnotations.clear();
        }
        target.maxStack = 1;
        target.maxLocals = 1;
    }

    static byte[] patchReplaySender(byte[] original) {
        ClassNode classNode = readClass(original);
        MethodNode target = method(classNode, "lambda$stop$2", MINECRAFT_DESCRIPTOR);
        AbstractInsnNode insertionPoint = null;
        for (AbstractInsnNode instruction = target.instructions.getFirst();
                instruction != null;
                instruction = instruction.getNext()) {
            if (instruction instanceof MethodInsnNode) {
                MethodInsnNode invocation = (MethodInsnNode) instruction;
                if (invocation.owner.equals("net/minecraft/client/world/ClientWorld")
                        && invocation.name.equals("sendQuittingDisconnectingPacket")
                        && invocation.desc.equals("()V")) {
                    insertionPoint = instruction;
                }
            }
        }
        target.instructions.insert(
                insertionPoint,
                new MethodInsnNode(
                        Opcodes.INVOKESTATIC,
                        RESET_HELPER,
                        "closePreviousServer",
                        MINECRAFT_DESCRIPTOR,
                        false));
        target.instructions.insert(insertionPoint, new VarInsnNode(Opcodes.ALOAD, 0));
        target.maxStack = Math.max(target.maxStack, 1);
        replaceMouseMoveWithStaticDelegate(
                method(
                        classNode,
                        "execMouseMove",
                        "(Lnet/minecraft/client/MouseHelper$State;)V"));
        patchInputImpulses(classNode);
        return writeClass(classNode);
    }

    private static void replaceMouseMoveWithStaticDelegate(MethodNode target) {
        target.instructions.clear();
        target.instructions.add(new VarInsnNode(Opcodes.ALOAD, 1));
        target.instructions.add(
                new MethodInsnNode(
                        Opcodes.INVOKESTATIC,
                        INPUT_HELPER,
                        "execMouseMove",
                        "(Lnet/minecraft/client/MouseHelper$State;)V",
                        false));
        target.instructions.add(new InsnNode(Opcodes.RETURN));
        target.tryCatchBlocks.clear();
        if (target.localVariables != null) {
            target.localVariables.clear();
        }
        if (target.visibleLocalVariableAnnotations != null) {
            target.visibleLocalVariableAnnotations.clear();
        }
        if (target.invisibleLocalVariableAnnotations != null) {
            target.invisibleLocalVariableAnnotations.clear();
        }
        target.maxStack = 1;
        target.maxLocals = 2;
    }

    private static void patchInputImpulses(ClassNode classNode) {
        MethodNode target = method(classNode, "execAction", "(Lcom/google/gson/JsonObject;)V");
        MethodInsnNode keyboardCall = null;
        MethodInsnNode mouseCall = null;
        for (AbstractInsnNode instruction = target.instructions.getFirst();
                instruction != null;
                instruction = instruction.getNext()) {
            if (!(instruction instanceof MethodInsnNode)) {
                continue;
            }
            MethodInsnNode invocation = (MethodInsnNode) instruction;
            if (invocation.owner.equals("net/minecraft/client/ReplaySender")
                    && invocation.name.equals("execKeyboard")
                    && invocation.desc.equals("(Lnet/minecraft/client/KeyboardListener$State;)V")) {
                keyboardCall = invocation;
            } else if (invocation.owner.equals("net/minecraft/client/ReplaySender")
                    && invocation.name.equals("execMouseButtons")
                    && invocation.desc.equals("(Ljava/util/Set;I)V")) {
                mouseCall = invocation;
            }
        }
        if (keyboardCall == null || mouseCall == null) {
            throw new IllegalStateException("ReplaySender input calls not found");
        }

        InsnList keyboardImpulse = new InsnList();
        keyboardImpulse.add(new VarInsnNode(Opcodes.ALOAD, 4));
        keyboardImpulse.add(
                new MethodInsnNode(
                        Opcodes.INVOKESTATIC,
                        INPUT_HELPER,
                        "execKeyboardImpulses",
                        "(Lnet/minecraft/client/KeyboardListener$State;)V",
                        false));
        target.instructions.insert(keyboardCall, keyboardImpulse);

        InsnList mouseImpulse = new InsnList();
        mouseImpulse.add(new VarInsnNode(Opcodes.ALOAD, 3));
        mouseImpulse.add(new VarInsnNode(Opcodes.ILOAD, 5));
        mouseImpulse.add(
                new MethodInsnNode(
                        Opcodes.INVOKESTATIC,
                        INPUT_HELPER,
                        "execMouseImpulses",
                        "(Lnet/minecraft/client/MouseHelper$State;I)V",
                        false));
        target.instructions.insert(mouseCall, mouseImpulse);
        target.maxStack = Math.max(target.maxStack, 2);
    }

    static byte[] patchBiomeTemperatureCache(byte[] original) {
        ClassNode classNode = readClass(original);
        MethodNode target = method(
                classNode,
                "getTemperature",
                "(Lnet/minecraft/util/math/BlockPos;)F");
        target.instructions.clear();
        target.instructions.add(new VarInsnNode(Opcodes.ALOAD, 0));
        target.instructions.add(new VarInsnNode(Opcodes.ALOAD, 1));
        target.instructions.add(
                new MethodInsnNode(
                        Opcodes.INVOKESPECIAL,
                        "net/minecraft/world/biome/Biome",
                        "getTemperatureAtPosition",
                        "(Lnet/minecraft/util/math/BlockPos;)F",
                        false));
        target.instructions.add(new InsnNode(Opcodes.FRETURN));
        target.tryCatchBlocks.clear();
        if (target.localVariables != null) {
            target.localVariables.clear();
        }
        target.maxStack = 2;
        target.maxLocals = 2;
        return writeClass(classNode);
    }
}
