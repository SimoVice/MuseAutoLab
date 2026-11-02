import { useEffect, useRef } from 'react';
import { useFrame, useThree } from '@react-three/fiber';
import type { Group } from 'three';
import GeometryPart from './GeometryPart';
import { coldJawOffsetsMm, sampleColdTransfer } from './coldTransferMotion';
import type { ColdTransferGeometry } from './coldTransferMotion';
import type { Component, LabwarePlate } from './types';
import type { MotionPlan } from './motionPlan';
import type { OperationSpec, Vec3 } from './operation';

const SCALE = 100;
type Extension = ColdTransferGeometry & { components: Component[]; lid_open_angle_deg: number };
const scaled = (point: Vec3, center: Vec3): Vec3 => point.map((value, index) => (value - center[index]) / SCALE) as Vec3;

/** The canonical plate primitives are drawn once, separately from the fixed holder. */
export default function ColdTransferScene({ extension, sample, plate, center, operation, selectedId, onSelect, visibleIds, renderPayload }: {
  extension: Extension; sample: Component; plate: LabwarePlate; center: Vec3;
  operation?: OperationSpec; selectedId: string | null; onSelect: (id: string) => void; visibleIds: string[] | null; renderPayload: boolean;
}) {
  const payloadRef = useRef<Group>(null), gripperRef = useRef<Group>(null), carriageRef = useRef<Group>(null);
  const leftRef = useRef<Group>(null), rightRef = useRef<Group>(null), lidRef = useRef<Group>(null), shaftRef = useRef<Group>(null);
  const invalidate = useThree((state) => state.invalidate);
  const parts = new Map(extension.components.map((part) => [part.id, part]));
  const lid = parts.get('cold-transfer-lid'), carriage = parts.get('cold-transfer-carriage'), gripper = parts.get('cold-transfer-gripper'), shaftPart = parts.get('cold-transfer-shaft');
  const timeline: MotionPlan | undefined = operation?.timeline;
  const active = timeline?.status === 'ready' && timeline.mode === 'cold-transfer';
  const pickup = extension.pickup_mm;
  const apply = () => {
    if (!payloadRef.current || !gripperRef.current || !carriageRef.current || !lidRef.current || !leftRef.current || !rightRef.current || !shaftRef.current || !carriage || !gripper || !shaftPart) return;
    const frame = active && timeline ? sampleColdTransfer(timeline, operation?.timeRef?.current ?? operation?.time_s ?? 0) : null;
    const gripperPosition: Vec3 = frame?.position_mm ?? [pickup[0], extension.transfer_height_mm, pickup[2]];
    const payloadPosition = frame?.payload_position_mm ?? pickup;
    payloadRef.current.position.set(...scaled(payloadPosition, center));
    const offset: Vec3 = [gripperPosition[0] - pickup[0], gripperPosition[1] - extension.transfer_height_mm, gripperPosition[2] - pickup[2]];
    gripperRef.current.position.set(...scaled([gripper.position[0] + offset[0], gripper.position[1] + offset[1], gripper.position[2] + offset[2]], center));
    carriageRef.current.position.set(...scaled([carriage.position[0] + offset[0], carriage.position[1], carriage.position[2] + offset[2]], center));
    const [leftOffset, rightOffset] = coldJawOffsetsMm(gripper, plate.profile.source_dimensions_mm[0], frame?.jaw_open ?? 1);
    leftRef.current.position.x = leftOffset / SCALE;
    rightRef.current.position.x = rightOffset / SCALE;
    lidRef.current.rotation.x = (frame?.lid_open ?? 0) * extension.lid_open_angle_deg * Math.PI / 180;
    const shaftTop = carriage.position[1] - carriage.size[1] / 2;
    const bridge = gripper.geometry?.primitives.find((primitive) => primitive.id === 'gripper-bridge');
    const shaftBottom = gripper.position[1] + offset[1] + (bridge ? bridge.position[1] + bridge.size[1] / 2 : gripper.size[1] / 2);
    const shaftLength = Math.max(0.1, shaftTop - shaftBottom);
    const shaft = scaled([gripperPosition[0], (shaftTop + shaftBottom) / 2, gripperPosition[2]], center);
    shaftRef.current.position.set(...shaft);
    shaftRef.current.scale.y = shaftLength / shaftPart.size[1];
  };
  useEffect(() => { apply(); invalidate(); });
  useFrame(() => { if (active && operation?.playing) { apply(); invalidate(); } });
  if (!lid || !carriage || !gripper || !shaftPart || !sample.geometry) return null;
  const singlePart = (part: Component, primitives: NonNullable<Component['geometry']>['primitives']): Component => ({ ...part, geometry: { schema_version: '1', primitives } });
  const platePart = singlePart(sample, sample.geometry.primitives.filter((primitive) => primitive.id.startsWith('reference-plate-')));
  const gripperPrimitives = gripper.geometry?.primitives ?? [];
  const left = gripperPrimitives.filter((primitive) => primitive.id === 'gripper-jaw-left');
  const right = gripperPrimitives.filter((primitive) => primitive.id === 'gripper-jaw-right');
  const bridge = gripperPrimitives.filter((primitive) => !primitive.id.startsWith('gripper-jaw-'));
  const occupied = new Set(plate.compatibility.occupied_wells);
  const zero: Vec3 = [0, 0, 0];
  const visible = (id: string) => !visibleIds || visibleIds.includes(id);
  return <group name="cold-transfer-concept">
    {extension.components.filter((part) => !['cold-transfer-lid', 'cold-transfer-carriage', 'cold-transfer-gripper', 'cold-transfer-shaft'].includes(part.id)).map((part) =>
      <group key={part.id} visible={visible(part.id)}><GeometryPart part={part} position={scaled(part.position, center)} selected={selectedId === part.id} onSelect={onSelect} /></group>)}
    <group visible={visible(lid.id)} position={scaled([lid.position[0], lid.position[1], lid.position[2] + lid.size[2] / 2], center)}>
      <group ref={lidRef} name="cold-cabinet-hinged-lid">
        <GeometryPart part={lid} position={[0, 0, -lid.size[2] / 2 / SCALE]} selected={selectedId === lid.id} onSelect={onSelect} />
      </group>
    </group>
    <group ref={carriageRef} visible={visible(carriage.id)} name="cold-transfer-moving-carriage"><GeometryPart part={carriage} position={zero} selected={selectedId === carriage.id} onSelect={onSelect} /></group>
    <group ref={shaftRef} visible={visible(shaftPart.id)} name="cold-transfer-telescoping-shaft"><GeometryPart part={shaftPart} position={zero} selected={selectedId === shaftPart.id} onSelect={onSelect} /></group>
    <group ref={gripperRef} visible={visible(gripper.id)} name="cold-transfer-moving-gripper">
      {bridge.length > 0 && <GeometryPart part={singlePart(gripper, bridge)} position={zero} selected={selectedId === gripper.id} onSelect={onSelect} />}
      <group ref={leftRef} name="cold-transfer-left-jaw">{left.length > 0 && <GeometryPart part={singlePart(gripper, left)} position={zero} selected={selectedId === gripper.id} onSelect={onSelect} />}</group>
      <group ref={rightRef} name="cold-transfer-right-jaw">{right.length > 0 && <GeometryPart part={singlePart(gripper, right)} position={zero} selected={selectedId === gripper.id} onSelect={onSelect} />}</group>
    </group>
    <group ref={payloadRef} visible={renderPayload && visible(sample.id)} name="cold-transfer-moving-plate">
      {renderPayload && <>
      <GeometryPart part={platePart} position={zero} selected={selectedId === sample.id} onSelect={onSelect} />
      {plate.derived.wells.filter((well) => occupied.has(well.label)).map((well) => <mesh key={well.label} name={`cold-occupied-well-${well.label}`}
        position={[well.app_x_mm / SCALE, (well.app_y_mm - 0.5) / SCALE, well.app_z_mm / SCALE]} rotation={[-Math.PI / 2, 0, 0]}>
        <circleGeometry args={[well.diameter_mm / SCALE * 0.42, 24]} /><meshStandardMaterial color="#087d7d" transparent opacity={0.75} />
      </mesh>)}
      </>}
    </group>
  </group>;
}
