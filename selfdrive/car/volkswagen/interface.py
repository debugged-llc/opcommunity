from cereal import car, arne182
#from selfdrive.config import Conversions as CV
from selfdrive.controls.lib.drive_helpers import create_event, EventTypes as ET
from selfdrive.car.volkswagen.values import CAR, BUTTON_STATES
from common.params import Params
from selfdrive.car import STD_CARGO_KG, scale_rot_inertia, scale_tire_stiffness, gen_empty_fingerprint
from selfdrive.car.interfaces import CarInterfaceBase

GEAR = car.CarState.GearShifter

class CarInterface(CarInterfaceBase):
  def __init__(self, CP, CarController, CarState):
    super().__init__(CP, CarController, CarState)

    self.displayMetricUnitsPrev = None
    self.buttonStatesPrev = BUTTON_STATES.copy()

  @staticmethod
  def compute_gb(accel, speed):
    return float(accel) / 4.0

  @staticmethod
  def get_params(candidate, fingerprint=gen_empty_fingerprint(), has_relay=False, car_fw=[]):
    ret = CarInterfaceBase.get_std_params(candidate, fingerprint, has_relay)

    # Applies to all models for now
    # if candidate in (CAR.VW_GOLF, CAR.SKODA_SUPERB_B8, CAR.VW_TOURAN):

    # Set common MQB parameters that will apply globally
    ret.carName = "volkswagen"
    ret.radarOffCan = True
    ret.safetyModel = car.CarParams.SafetyModel.volkswagen

    # Additional common MQB parameters that may be overridden per-vehicle
    ret.steerRateCost = 1.0
    ret.steerActuatorDelay = 0.05  # Hopefully all MQB racks are similar here
    ret.steerLimitTimer = 0.4

    ret.steerMaxBP = [0.]  # m/s
    ret.steerMaxV = [1.]


    # ret.lateralTuning.pid.kpBP = [0., 15 * CV.KPH_TO_MS, 50 * CV.KPH_TO_MS]
    # ret.lateralTuning.pid.kiBP = [0., 15 * CV.KPH_TO_MS, 50 * CV.KPH_TO_MS]
    # ret.lateralTuning.pid.kpV = [0.15, 0.25, 0.60]
    # ret.lateralTuning.pid.kiV = [0.05, 0.05, 0.05]

    ret.centerToFront = ret.wheelbase * 0.45
    ret.steerRatio = 15.6
    ret.steerRatioRear = 0.

    ret.lateralTuning.pid.kf = 0.00006
    ret.lateralTuning.pid.kpBP = [0.]
    ret.lateralTuning.pid.kiBP = [0.]
    ret.lateralTuning.pid.kpV = [0.6]
    ret.lateralTuning.pid.kiV = [0.2]

    ret.enableCamera = True # Stock camera detection doesn't apply to VW
    ret.transmissionType = car.CarParams.TransmissionType.automatic
    # ret.enableCruise = True  # Stock ACC still controls acceleration and braking
    # ret.openpilotLongitudinalControl = False
    # ret.steerControlType = car.CarParams.SteerControlType.torque

    # Define default values across the MQB range, 
    # redefined per model bellow.
    # Commented our for now as we don't allow unknown models for now.

    # ret.mass = 1500 + STD_CARGO_KG
    # ret.wheelbase = 2.64
    # tire_stiffness_factor = 1.0

    # Refine parameters for each vehicle.
    if candidate == CAR.GOLF:

      ret.mass = 1500 + STD_CARGO_KG
      ret.wheelbase = 2.64
      tire_stiffness_factor = 1.0

    elif candidate == CAR.VW_TOURAN:

      ret.mass = 1650 + STD_CARGO_KG
      ret.wheelbase = 2.79
      tire_stiffness_factor = 0.8

    elif candidate == CAR.SKODA_SUPERB_B8:

      ret.mass = 1700 + STD_CARGO_KG
      ret.wheelbase = 2.85
      tire_stiffness_factor = 0.8

    # Not sure if I should simply exit or raise an error
    else:
      raise ValueError("Unsupported car %s" % candidate)

    # TODO: get actual value, for now starting with reasonable value for
    # civic and scaling by mass and wheelbase
    ret.rotationalInertia = scale_rot_inertia(ret.mass, ret.wheelbase)

    # TODO: start from empirically derived lateral slip stiffness for the civic and scale by
    # mass and CG position, so all cars will have approximately similar dyn behaviors
    ret.tireStiffnessFront, ret.tireStiffnessRear = scale_tire_stiffness(ret.mass, ret.wheelbase, ret.centerToFront,
                                                                         tire_stiffness_factor=tire_stiffness_factor)

    return ret

  # returns a car.CarState
  def update(self, c, can_strings):
    canMonoTimes = []

    ret_arne182 = arne182.CarStateArne182.new_message()
    buttonEvents = []
    params = Params()


    # Process the most recent CAN message traffic, and check for validity
    # The camera CAN has no signals we use at this time, but we process it
    # anyway so we can test connectivity with can_valid
    self.cp.update_strings(can_strings)
    self.cp_cam.update_strings(can_strings)

    ret = self.CS.update(self.cp)
    ret.canValid = self.cp.can_valid and self.cp_cam.can_valid
    ret.steeringRateLimited = self.CC.steer_rate_limited if self.CC is not None else False

    # Update the EON metric configuration to match the car at first startup,
    # or if there's been a change.
    if self.CS.displayMetricUnits != self.displayMetricUnitsPrev:
      params.put("IsMetric", "1" if self.CS.displayMetricUnits else "0")

    # Check for and process state-change events (button press or release) from
    # the turn stalk switch or ACC steering wheel/control stalk buttons.
    for button in self.CS.buttonStates:
      if self.CS.buttonStates[button] != self.buttonStatesPrev[button]:
        be = car.CarState.ButtonEvent.new_message()
        be.type = button
        be.pressed = self.CS.buttonStates[button]
        buttonEvents.append(be)

    events, eventsArne182 = self.create_common_events(ret, extra_gears=[GEAR.eco, GEAR.sport])

    # Vehicle health and operation safety checks
    if self.CS.parkingBrakeSet:
      events.append(create_event('parkBrake', [ET.NO_ENTRY, ET.USER_DISABLE]))
    if self.CS.steeringFault:
      events.append(create_event('steerTempUnavailable', [ET.NO_ENTRY, ET.WARNING]))

    # Engagement and longitudinal control using stock ACC. Make sure OP is
    # disengaged if stock ACC is disengaged.
    if not ret.cruiseState.enabled:
      events.append(create_event('pcmDisable', [ET.USER_DISABLE]))
    # Attempt OP engagement only on rising edge of stock ACC engagement.
    elif not self.cruise_enabled_prev:
      events.append(create_event('pcmEnable', [ET.ENABLE]))
    ret_arne182.events = eventsArne182
    ret.events = events
    ret.buttonEvents = buttonEvents
    ret.canMonoTimes = canMonoTimes

    # update previous car states
    self.gas_pressed_prev = ret.gasPressed
    self.brake_pressed_prev = ret.brakePressed
    self.cruise_enabled_prev = ret.cruiseState.enabled
    self.displayMetricUnitsPrev = self.CS.displayMetricUnits
    self.buttonStatesPrev = self.CS.buttonStates.copy()

    self.CS.out = ret.as_reader()
    return self.CS.out, ret_arne182.as_reader()


  def apply(self, c):
    can_sends = self.CC.update(c.enabled, self.CS, self.frame, c.actuators,
                    c.hudControl.visualAlert,
                    c.hudControl.audibleAlert,
                    c.hudControl.leftLaneVisible,
                    c.hudControl.rightLaneVisible)
    self.frame += 1
    return can_sends
